"""
Tests for Doorstep Resolve Streamable HTTP MCP Client (Milestone A).

Validates:
1. Protocol initialization and server metadata handshake.
2. Tool discovery via list_tools().
3. Tool execution for get_order (success, not found, empty input).
4. Tool execution for check_replacement_options (feasible route, missed deadline, invalid input).
5. Protocol telemetry capture in MCPToolCallTrace (tool name, arguments, response, duration, status, timestamp).
6. Tool errors and unknown tool invocation handling.
7. Clean session lifecycle and resource cleanup via both context manager and explicit connect/close.
"""

import pytest
import anyio
import httpx2
from datetime import datetime

from doorstep_resolve.db import Database
from doorstep_resolve.server import create_mcp_server
from doorstep_resolve.mcp_client import DoorstepMCPClient, MCPToolCallTrace


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database populated with default scenario data."""
    db_file = tmp_path / "test_doorstep_client.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def mcp_server_and_transport(test_db):
    """
    Sets up an in-process MCP server with ASGITransport for isolated client testing.
    Avoids port collisions, deadlocks, and network dependencies.
    """
    server = create_mcp_server(db=test_db)
    app = server.streamable_http_app()
    transport = httpx2.ASGITransport(app=app)
    return server, transport


class TestDoorstepMCPClient:
    """Milestone A verification suite for the Streamable HTTP MCP Client."""

    @pytest.mark.anyio
    async def test_session_initialization_and_metadata(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client) as client:
                    assert client.is_connected is True
                    assert client.server_info is not None
                    assert client.server_info["name"] == "doorstep-resolve"
                    assert client.server_info["version"] == "1.0.0"

    @pytest.mark.anyio
    async def test_tool_discovery_list_tools(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client) as client:
                    tools = await client.list_tools()
                    tool_names = [t["name"] for t in tools]

                    assert "get_order" in tool_names
                    assert "check_replacement_options" in tool_names
                    assert "confirm_resolution" in tool_names
                    assert "get_case_history" in tool_names

                    get_order_tool = next(t for t in tools if t["name"] == "get_order")
                    assert "order_id" in get_order_tool["description"].lower() or "persistent" in get_order_tool["description"].lower()

    @pytest.mark.anyio
    async def test_get_order_success_trace(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client) as client:
                    trace = await client.call_tool("get_order", {"order_id": "ORD-1001"})

                    assert isinstance(trace, MCPToolCallTrace)
                    assert trace.tool == "get_order"
                    assert trace.arguments == {"order_id": "ORD-1001"}
                    assert trace.status == "SUCCESS"
                    assert trace.is_error is False
                    assert trace.duration_ms >= 1
                    assert trace.durationMs == trace.duration_ms
                    assert trace.timestamp is not None

                    # Check payload returned over MCP protocol
                    order = trace.response["order"]
                    assert order["order_id"] == "ORD-1001"
                    assert order["item_id"] == "SKU-HEADPHONES-PRO"
                    assert order["price"] == 199.99

                    # Verify dictionary export matches frontend ActivityTraceDrawer format
                    trace_dict = trace.to_dict()
                    assert trace_dict["tool"] == "get_order"
                    assert trace_dict["status"] == "SUCCESS"
                    assert "durationMs" in trace_dict
                    assert "response" in trace_dict

    @pytest.mark.anyio
    async def test_get_order_not_found_trace(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client) as client:
                    trace = await client.call_tool("get_order", {"order_id": "ORD-NONEXISTENT-999"})

                    assert trace.tool == "get_order"
                    assert trace.status == "NOT_FOUND"
                    assert "not found" in trace.response["error"].lower()

    @pytest.mark.anyio
    async def test_get_order_empty_id_error_trace(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client) as client:
                    trace = await client.call_tool("get_order", {"order_id": ""})

                    assert trace.status == "ERROR"
                    assert trace.is_error is True
                    assert "empty" in trace.response["error"].lower() or "provided" in trace.response["error"].lower()

    @pytest.mark.anyio
    async def test_check_replacement_options_scenario_1_feasible(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client) as client:
                    trace = await client.call_tool(
                        "check_replacement_options",
                        {
                            "order_id": "ORD-1001",
                            "customer_deadline": "2026-10-22T18:00:00",
                            "current_time": "2026-10-20T10:00:00",
                        },
                    )

                    assert trace.tool == "check_replacement_options"
                    assert trace.status == "SUCCESS"
                    assert trace.is_error is False
                    assert trace.duration_ms >= 1

                    res = trace.response
                    assert res["status"] == "SUCCESS"
                    assert res["meets_any_option"] is True
                    assert res["options_count"] == 1
                    top = res["top_option"]
                    assert top["eligible"] is True
                    assert top["meets_deadline"] is True
                    assert "Promise safe" in " ".join(top["evidence"])

    @pytest.mark.anyio
    async def test_check_replacement_options_scenario_2_missed_deadline(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client) as client:
                    trace = await client.call_tool(
                        "check_replacement_options",
                        {
                            "order_id": "ORD-1002",
                            "customer_deadline": "2026-10-22T12:00:00",
                            "current_time": "2026-10-20T17:30:00",
                        },
                    )

                    assert trace.tool == "check_replacement_options"
                    assert trace.status == "SUCCESS"
                    res = trace.response
                    assert res["meets_any_option"] is False
                    top = res["top_option"]
                    assert top["eligible"] is True
                    assert top["meets_deadline"] is False
                    assert "Fails deadline constraint" in " ".join(top["evidence"])

    @pytest.mark.anyio
    async def test_check_replacement_options_invalid_deadline_format(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client) as client:
                    trace = await client.call_tool(
                        "check_replacement_options",
                        {
                            "order_id": "ORD-1001",
                            "customer_deadline": "INVALID-NOT-ISO-DATE",
                        },
                    )

                    assert trace.status == "INVALID_INPUT"
                    assert trace.is_error is True
                    assert "Invalid ISO format" in trace.response["error"]

    @pytest.mark.anyio
    async def test_call_unknown_tool_graceful_error(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client) as client:
                    trace = await client.call_tool("non_existent_tool_xyz", {"foo": "bar"})

                    assert trace.tool == "non_existent_tool_xyz"
                    assert trace.is_error is True
                    assert trace.status == "ERROR"
                    assert "error" in trace.response

    @pytest.mark.anyio
    async def test_explicit_lifecycle_connect_and_close(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                client = DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client)
                assert client.is_connected is False

                # Connect
                await client.connect()
                assert client.is_connected is True
                assert client.session is not None

                # Invoke tool
                trace = await client.call_tool("get_order", {"order_id": "ORD-1001"})
                assert trace.status == "SUCCESS"

                # Close
                await client.close()
                assert client.is_connected is False

                # Calling session on closed client raises RuntimeError
                with pytest.raises(RuntimeError, match="not connected"):
                    _ = client.session

    @pytest.mark.anyio
    async def test_context_manager_cleanup(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        client_ref = None
        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with DoorstepMCPClient("http://127.0.0.1:8000/mcp", http_client=http_client) as client:
                    client_ref = client
                    assert client.is_connected is True

                # Exited context manager
                assert client_ref.is_connected is False
