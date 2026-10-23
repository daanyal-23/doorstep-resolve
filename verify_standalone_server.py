"""
Verification script for Doorstep Resolve standalone server process.

Tests:
1. Launching server as standalone process
2. Real MCP client initialization over Streamable HTTP (/mcp)
3. Tool discovery and tool calls
4. Server restart and verification of persistence across restarts
5. Idempotent retries across restarts
"""

import anyio
import httpx2
import subprocess
import time
import sys
import uuid
import json
from pathlib import Path

from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession

SERVER_PORT = 8011
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}/mcp"


def start_server_process():
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "doorstep_resolve.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(SERVER_PORT),
        "--log-level",
        "warning",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # Wait for server to bind port
    for _ in range(30):
        time.sleep(0.3)
        if proc.poll() is not None:
            stdout, stderr = proc.communicate()
            raise RuntimeError(f"Server process terminated prematurely with code {proc.returncode}.\nSTDOUT: {stdout}\nSTDERR: {stderr}")
        try:
            with httpx2.Client(timeout=1.0) as client:
                resp = client.get(f"http://127.0.0.1:{SERVER_PORT}/mcp")
                if resp.status_code in (200, 400, 405, 421):
                    break
        except Exception:
            pass
    return proc


async def run_client_workflow(idempotency_key: str):
    async with httpx2.AsyncClient(base_url=f"http://127.0.0.1:{SERVER_PORT}") as http_client:
        async with streamable_http_client(SERVER_URL, http_client=http_client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init_res = await session.initialize()
                print(f"[Client] Initialized session with server: {init_res.server_info.name} v{init_res.server_info.version}")

                tools_res = await session.list_tools()
                tool_names = [t.name for t in tools_res.tools]
                print(f"[Client] Discovered tools: {tool_names}")
                assert "get_order" in tool_names
                assert "check_replacement_options" in tool_names
                assert "confirm_resolution" in tool_names
                assert "get_case_history" in tool_names

                # 1. get_order
                res_order = await session.call_tool("get_order", {"order_id": "ORD-1001"})
                order_data = json.loads(res_order.content[0].text)
                print(f"[Client] get_order status: {order_data['status']}")
                assert order_data["status"] == "SUCCESS"

                # 2. check_replacement_options
                res_opts = await session.call_tool(
                    "check_replacement_options",
                    {
                        "order_id": "ORD-1001",
                        "customer_deadline": "2026-10-22T18:00:00",
                        "current_time": "2026-10-20T10:00:00",
                    },
                )
                opts_data = json.loads(res_opts.content[0].text)
                print(f"[Client] check_replacement_options: {opts_data['options_count']} options, meets_any: {opts_data['meets_any_option']}")
                assert opts_data["meets_any_option"] is True

                # 3. confirm_resolution
                res_confirm = await session.call_tool(
                    "confirm_resolution",
                    {
                        "order_id": "ORD-1001",
                        "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
                        "customer_agreed": True,
                        "idempotency_key": idempotency_key,
                        "customer_notes": "Standalone verification test.",
                    },
                )
                confirm_data = json.loads(res_confirm.content[0].text)
                print(f"[Client] confirm_resolution status: {confirm_data['status']}, replay: {confirm_data['idempotent_replay']}")
                assert confirm_data["status"] == "CONFIRMED"
                assert confirm_data["idempotent_replay"] is False


async def run_retry_workflow(idempotency_key: str):
    async with httpx2.AsyncClient(base_url=f"http://127.0.0.1:{SERVER_PORT}") as http_client:
        async with streamable_http_client(SERVER_URL, http_client=http_client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Re-send same idempotency key across restart
                res_retry = await session.call_tool(
                    "confirm_resolution",
                    {
                        "order_id": "ORD-1001",
                        "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
                        "customer_agreed": True,
                        "idempotency_key": idempotency_key,
                    },
                )
                retry_data = json.loads(res_retry.content[0].text)
                print(f"[Client after restart] Retry status: {retry_data['status']}, replay: {retry_data['idempotent_replay']}")
                assert retry_data["status"] == "ALREADY_CONFIRMED"
                assert retry_data["idempotent_replay"] is True

                # Query history across restart
                res_hist = await session.call_tool("get_case_history", {"order_id": "ORD-1001"})
                hist_data = json.loads(res_hist.content[0].text)
                print(f"[Client after restart] History events persisted: {hist_data['event_count']}")
                assert hist_data["event_count"] >= 2


def main():
    test_key = f"TEST-RESTART-{uuid.uuid4().hex[:8]}"
    print("=" * 60)
    print("STARTING STANDALONE SERVER TEST...")
    print("=" * 60)

    proc1 = start_server_process()
    try:
        print("[Server] Standalone process 1 started (PID:", proc1.pid, ")")
        anyio.run(run_client_workflow, test_key)
    finally:
        proc1.terminate()
        proc1.wait()
        print("[Server] Standalone process 1 terminated.")

    print("\n--- RESTARTING STANDALONE SERVER (Verifying SQLite Persistence) ---")
    proc2 = start_server_process()
    try:
        print("[Server] Standalone process 2 started (PID:", proc2.pid, ")")
        anyio.run(run_retry_workflow, test_key)
    finally:
        proc2.terminate()
        proc2.wait()
        print("[Server] Standalone process 2 terminated.")

    print("=" * 60)
    print("STANDALONE SERVER AND PERSISTENCE VERIFICATION PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    main()
