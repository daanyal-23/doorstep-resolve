"""
Doorstep Resolve - Streamable HTTP MCP Client.

Provides a robust client for connecting to the Doorstep Resolve Streamable HTTP MCP
endpoint over the official MCP protocol (JSON-RPC over SSE/HTTP).

Captures:
- Real MCP tool execution with structured payloads
- Protocol-level telemetry: tool name, arguments, structured result, duration, status
- Clean session lifecycle (initialize, call_tool, list_tools, shutdown)
"""

import json
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


@dataclass
class MCPToolCallTrace:
    """Structured telemetry record of a single genuine MCP tool invocation."""
    tool: str
    arguments: Dict[str, Any]
    response: Dict[str, Any]
    duration_ms: int
    timestamp: str
    status: str
    is_error: bool = False

    @property
    def durationMs(self) -> int:
        """CamelCase alias matching frontend ActivityTraceDrawer expectations."""
        return self.duration_ms

    def to_dict(self) -> Dict[str, Any]:
        """Convert trace event to standard dictionary format."""
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "response": self.response,
            "durationMs": self.duration_ms,
            "timestamp": self.timestamp,
            "status": self.status,
            "is_error": self.is_error,
        }


class DoorstepMCPClient:
    """
    Client for interacting with the Doorstep Resolve MCP Server via Streamable HTTP.

    Supports:
    - Async context manager usage (`async with DoorstepMCPClient(...) as client:`)
    - Explicit `connect()` and `close()` lifecycle methods
    - Discovering tools via `list_tools()`
    - Executing tools via `call_tool(tool_name, arguments)` with full telemetry capture
    - Loopback HTTP against running servers as well as in-process ASGI transports
    """

    def __init__(
        self,
        server_url: str = "http://127.0.0.1:8000/mcp",
        http_client: Optional[httpx2.AsyncClient] = None,
        timeout: float = 30.0,
    ):
        self.server_url = server_url
        self._external_http_client = http_client
        self._timeout = timeout
        self._exit_stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        self._server_info: Optional[Dict[str, str]] = None
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self._session is not None

    @property
    def session(self) -> ClientSession:
        if not self._session or not self._is_connected:
            raise RuntimeError("MCP client is not connected. Call connect() or use async context manager.")
        return self._session

    @property
    def server_info(self) -> Optional[Dict[str, str]]:
        return self._server_info

    async def connect(self) -> "DoorstepMCPClient":
        """Establishes Streamable HTTP connection and performs MCP initialization handshake."""
        if self._is_connected:
            return self

        self._exit_stack = AsyncExitStack()
        try:
            # 1. Determine HTTP client
            if self._external_http_client is not None:
                client = self._external_http_client
            else:
                client = await self._exit_stack.enter_async_context(
                    httpx2.AsyncClient(timeout=self._timeout)
                )

            # 2. Enter streamable_http_client
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                streamable_http_client(self.server_url, http_client=client)
            )

            # 3. Enter ClientSession
            session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )

            # 4. Initialize MCP protocol handshake
            init_res = await session.initialize()
            self._session = session
            self._server_info = {
                "name": getattr(init_res.server_info, "name", "unknown"),
                "version": getattr(init_res.server_info, "version", "unknown"),
            }
            self._is_connected = True
            return self

        except Exception:
            if self._exit_stack:
                await self._exit_stack.aclose()
                self._exit_stack = None
            self._session = None
            self._is_connected = False
            raise

    async def close(self) -> None:
        """Closes the MCP session and frees transport streams cleanly."""
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            finally:
                self._exit_stack = None
                self._session = None
                self._is_connected = False

    async def __aenter__(self) -> "DoorstepMCPClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List registered tools from the MCP server."""
        tools_res = await self.session.list_tools()
        tools_list = []
        for t in tools_res.tools:
            tools_list.append({
                "name": t.name,
                "description": t.description,
                "inputSchema": getattr(t, "inputSchema", {}),
            })
        return tools_list

    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> MCPToolCallTrace:
        """
        Invokes an MCP tool through the protocol and captures full telemetry.
        """
        args = arguments or {}
        start_time = time.perf_counter()
        timestamp = datetime.now().strftime("%H:%M:%S")

        try:
            raw_res = await self.session.call_tool(tool_name, args)
            duration_ms = max(1, round((time.perf_counter() - start_time) * 1000))

            is_error = getattr(raw_res, "isError", False) or False
            content = getattr(raw_res, "content", [])

            # Extract structured response from MCP content block
            if content and hasattr(content[0], "text"):
                text = content[0].text
                try:
                    payload = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    payload = {"raw_text": text}
            else:
                payload = {"empty": True}

            # Determine semantic status
            if is_error:
                status = "ERROR"
                if isinstance(payload, dict) and "error" not in payload:
                    payload["error"] = payload.get("raw_text", "Tool execution failed")
            elif isinstance(payload, dict) and "status" in payload:
                status = payload["status"]
            elif isinstance(payload, dict) and "raw_text" in payload and any(err_word in payload["raw_text"].lower() for err_word in ("unknown tool", "error", "exception", "failed")):
                status = "ERROR"
                is_error = True
                payload["error"] = payload["raw_text"]
            else:
                status = "SUCCESS"

            return MCPToolCallTrace(
                tool=tool_name,
                arguments=args,
                response=payload,
                duration_ms=duration_ms,
                timestamp=timestamp,
                status=status,
                is_error=is_error or (status in ("ERROR", "RESOLVER_ERROR", "INVALID_INPUT")),
            )

        except Exception as exc:
            duration_ms = max(1, round((time.perf_counter() - start_time) * 1000))
            return MCPToolCallTrace(
                tool=tool_name,
                arguments=args,
                response={"error": str(exc), "status": "ERROR"},
                duration_ms=duration_ms,
                timestamp=timestamp,
                status="ERROR",
                is_error=True,
            )
