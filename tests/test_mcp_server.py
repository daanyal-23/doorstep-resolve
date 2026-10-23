"""
Tests for Doorstep Resolve Streamable HTTP MCP Server.

Validates:
- Tool inputs and schema validation
- Database persistence in SQLite
- Resolver integration for all scenario types
- Explicit confirmation requirement
- Idempotency and duplicate retry handling
- Audit trail logging via get_case_history
- End-to-end Streamable HTTP MCP client session initialization, tool discovery, and tool execution
"""

import json
import pytest
import anyio
import httpx2
from datetime import datetime, timezone

from doorstep_resolve.db import Database
from doorstep_resolve.server import create_mcp_server, create_app
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database populated with default scenario data."""
    db_file = tmp_path / "test_doorstep.db"
    return Database(db_path=str(db_file))


class TestMCPServerDirectTools:
    """Direct tests for the MCP server tool functions."""

    def test_get_order_success_and_not_found(self, test_db):
        server = create_mcp_server(db=test_db)

        # Successful order lookup
        res = server.get_order("ORD-1001")
        assert res["status"] == "SUCCESS"
        assert res["order"]["order_id"] == "ORD-1001"
        assert res["order"]["item_id"] == "SKU-HEADPHONES-PRO"
        assert res["order"]["price"] == 199.99

        # Order not found
        res_404 = server.get_order("ORD-UNKNOWN-999")
        assert res_404["status"] == "NOT_FOUND"
        assert "not found" in res_404["error"].lower()

        # Empty order ID
        res_empty = server.get_order("")
        assert res_empty["status"] == "ERROR"

    def test_check_replacement_options_scenario_1_meets_deadline(self, test_db):
        server = create_mcp_server(db=test_db)
        res = server.check_replacement_options(
            order_id="ORD-1001",
            customer_deadline="2026-10-22T18:00:00",
            current_time="2026-10-20T10:00:00",
        )
        assert res["status"] == "SUCCESS"
        assert res["meets_any_option"] is True
        assert res["options_count"] == 1
        opt_ids = [o["option_id"] for o in res["options"]]
        assert len(opt_ids) == len(set(opt_ids)), "Option IDs must be unique"
        top = res["top_option"]
        assert top["eligible"] is True
        assert top["meets_deadline"] is True
        assert "Promise safe" in " ".join(top["evidence"])
        assert "before cutoff 17:00" in " ".join(top["evidence"])

    def test_check_replacement_options_scenario_2_misses_deadline(self, test_db):
        server = create_mcp_server(db=test_db)
        # ORD-1002 with 48h ground transit and past 16:00 cutoff
        res = server.check_replacement_options(
            order_id="ORD-1002",
            customer_deadline="2026-10-22T12:00:00",
            current_time="2026-10-20T17:30:00",
        )
        assert res["status"] == "SUCCESS"
        assert res["meets_any_option"] is False
        top = res["top_option"]
        assert top["eligible"] is True
        assert top["meets_deadline"] is False
        assert "Fails deadline constraint" in " ".join(top["evidence"])

    def test_check_replacement_options_scenario_3_out_of_stock(self, test_db):
        server = create_mcp_server(db=test_db)
        # ORD-1003 has 0 inventory
        res = server.check_replacement_options(
            order_id="ORD-1003",
            customer_deadline="2026-10-24T18:00:00",
            current_time="2026-10-20T11:00:00",
        )
        assert res["status"] == "SUCCESS"
        assert res["meets_any_option"] is False
        top = res["top_option"]
        assert top["eligible"] is False
        assert top["action_type"] == "REPLACEMENT_OUT_OF_STOCK"

    def test_check_replacement_options_scenario_4_window_expired(self, test_db):
        server = create_mcp_server(db=test_db)
        # ORD-1004 delivered on 2026-09-10 (40 days ago, 30-day window)
        res = server.check_replacement_options(
            order_id="ORD-1004",
            customer_deadline="2026-10-23T12:00:00",
            current_time="2026-10-20T11:00:00",
        )
        assert res["status"] == "SUCCESS"
        assert res["meets_any_option"] is False
        top = res["top_option"]
        assert top["eligible"] is False
        assert top["action_type"] == "REPLACEMENT_WINDOW_EXPIRED"

    def test_check_replacement_options_scenario_5_expedited_preferred(self, test_db):
        server = create_mcp_server(db=test_db)
        # ORD-1005: Standard misses deadline, Expedited meets it
        res = server.check_replacement_options(
            order_id="ORD-1005",
            customer_deadline="2026-10-21T17:00:00",
            current_time="2026-10-20T13:00:00",
        )
        assert res["status"] == "SUCCESS"
        assert res["meets_any_option"] is True
        assert res["options_count"] == 2
        top = res["top_option"]
        assert top["action_type"] == "REPLACEMENT_EXPEDITED"
        assert top["meets_deadline"] is True
        assert top["cost"] == 14.99

    def test_check_replacement_options_invalid_inputs(self, test_db):
        server = create_mcp_server(db=test_db)
        # Invalid date format
        res = server.check_replacement_options(
            order_id="ORD-1001",
            customer_deadline="not-a-date",
        )
        assert res["status"] == "INVALID_INPUT"
        assert "Invalid ISO format" in res["error"]

    def test_confirm_resolution_requires_explicit_agreement(self, test_db):
        server = create_mcp_server(db=test_db)
        res = server.confirm_resolution(
            order_id="ORD-1001",
            option_id="REPLACE_WH-EAST-1_STANDARD_GROUND",
            customer_agreed=False,  # Agreement NOT given
            idempotency_key="IDEMP-NO-AGREE-1",
        )
        assert res["status"] == "CONFIRMATION_REQUIRED"
        assert "explicit customer agreement" in res["error"]

        # Verify audit history logged the CONFIRMATION_REJECTED event
        history = server.get_case_history(order_id="ORD-1001")
        event_types = [ev["event_type"] for ev in history["events"]]
        assert "CONFIRMATION_REJECTED" in event_types

    def test_test_rejected_flow_after_confirmation_uses_fresh_key(self, test_db):
        server = create_mcp_server(db=test_db)
        key_confirmed = "IDEMP-CONFIRMED-001"
        key_rejected = "IDEMP-REJECT-002"

        # 1. Confirm resolution
        res_conf = server.confirm_resolution(
            order_id="ORD-1001",
            option_id="REPLACE_WH-EAST-1_STANDARD_GROUND",
            customer_agreed=True,
            idempotency_key=key_confirmed,
        )
        assert res_conf["status"] == "CONFIRMED"

        # 2. Test duplicate replay with confirmed key -> ALREADY_CONFIRMED
        res_replay = server.confirm_resolution(
            order_id="ORD-1001",
            option_id="REPLACE_WH-EAST-1_STANDARD_GROUND",
            customer_agreed=True,
            idempotency_key=key_confirmed,
        )
        assert res_replay["status"] == "ALREADY_CONFIRMED"
        assert res_replay["idempotent_replay"] is True

        # 3. Test rejected flow with fresh key -> CONFIRMATION_REQUIRED (not ALREADY_CONFIRMED)
        res_reject = server.confirm_resolution(
            order_id="ORD-1001",
            option_id="REPLACE_WH-EAST-1_STANDARD_GROUND",
            customer_agreed=False,
            idempotency_key=key_rejected,
        )
        assert res_reject["status"] == "CONFIRMATION_REQUIRED"
        assert res_reject.get("idempotent_replay") is not True

        # 4. Check case history has all 3 distinct events
        history = server.get_case_history(order_id="ORD-1001")
        event_types = [ev["event_type"] for ev in history["events"]]
        assert "RESOLUTION_CONFIRMED" in event_types
        assert "IDEMPOTENT_RETRY_DETECTED" in event_types
        assert "CONFIRMATION_REJECTED" in event_types

    def test_confirm_resolution_requires_idempotency_key(self, test_db):
        server = create_mcp_server(db=test_db)
        res = server.confirm_resolution(
            order_id="ORD-1001",
            option_id="REPLACE_WH-EAST-1_STANDARD_GROUND",
            customer_agreed=True,
            idempotency_key="",  # Missing key
        )
        assert res["status"] == "ERROR"
        assert "idempotency_key is required" in res["error"]

    def test_confirm_resolution_idempotency_duplicate_retries(self, test_db):
        server = create_mcp_server(db=test_db)
        key = "IDEMP-SAFE-RETRY-007"

        # First confirmation
        first_call = server.confirm_resolution(
            order_id="ORD-1001",
            option_id="REPLACE_WH-EAST-1_STANDARD_GROUND",
            customer_agreed=True,
            idempotency_key=key,
            customer_notes="Customer confirmed replacement delivery.",
        )
        assert first_call["status"] == "CONFIRMED"
        assert first_call["idempotent_replay"] is False
        assert "simulated_fulfillment" in first_call
        assert first_call["resolution"]["idempotency_key"] == key

        # Second confirmation with exact same key (retry)
        second_call = server.confirm_resolution(
            order_id="ORD-1001",
            option_id="REPLACE_WH-EAST-1_STANDARD_GROUND",
            customer_agreed=True,
            idempotency_key=key,
            customer_notes="Customer confirmed replacement delivery.",
        )
        assert second_call["status"] == "ALREADY_CONFIRMED"
        assert second_call["idempotent_replay"] is True
        assert second_call["resolution"]["idempotency_key"] == key
        assert "Duplicate action prevented" in second_call["message"]

        # Verify audit history logged the duplicate retry
        history = server.get_case_history(order_id="ORD-1001")
        event_types = [ev["event_type"] for ev in history["events"]]
        assert "RESOLUTION_CONFIRMED" in event_types
        assert "IDEMPOTENT_RETRY_DETECTED" in event_types

    def test_get_case_history_audit_trail(self, test_db):
        server = create_mcp_server(db=test_db)

        # 1. Check options
        check_res = server.check_replacement_options(
            order_id="ORD-1001",
            customer_deadline="2026-10-22T18:00:00",
            current_time="2026-10-20T10:00:00",
        )
        case_id = check_res["case_id"]

        # 2. Confirm resolution
        server.confirm_resolution(
            order_id="ORD-1001",
            option_id="REPLACE_WH-EAST-1_STANDARD_GROUND",
            customer_agreed=True,
            idempotency_key="IDEMP-HIST-1",
            case_id=case_id,
        )

        # Query history
        hist = server.get_case_history(order_id="ORD-1001")
        assert hist["status"] == "SUCCESS"
        assert hist["event_count"] >= 2
        events = hist["events"]
        assert any(e["event_type"] == "OPTIONS_CHECKED" for e in events)
        assert any(e["event_type"] == "RESOLUTION_CONFIRMED" for e in events)


class TestStreamableHTTPMCPEndpoint:
    """End-to-end integration test with a genuine MCP Client over Streamable HTTP."""

    @pytest.mark.anyio
    async def test_genuine_mcp_client_streamable_http_session(self, test_db):
        """
        Validates that a real MCP ClientSession connects to /mcp over Streamable HTTP,
        initializes the protocol, inspects tools, and calls all registered tools.
        """
        server = create_mcp_server(db=test_db)
        app = server.streamable_http_app()

        transport = httpx2.ASGITransport(app=app)
        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                async with streamable_http_client(
                    "http://127.0.0.1:8000/mcp", http_client=http_client
                ) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        # 1. Initialize MCP Protocol
                        init_res = await session.initialize()
                        assert init_res.server_info.name == "doorstep-resolve"
                        assert init_res.server_info.version == "1.0.0"

                        # 2. List & Inspect Registered Tools
                        tools_res = await session.list_tools()
                        tool_names = [t.name for t in tools_res.tools]
                        assert "get_order" in tool_names
                        assert "check_replacement_options" in tool_names
                        assert "confirm_resolution" in tool_names
                        assert "get_case_history" in tool_names

                        # 3. Call get_order via MCP Protocol
                        order_call = await session.call_tool("get_order", {"order_id": "ORD-1001"})
                        assert len(order_call.content) > 0
                        order_payload = json.loads(order_call.content[0].text)
                        assert order_payload["status"] == "SUCCESS"
                        assert order_payload["order"]["order_id"] == "ORD-1001"

                        # 4. Call check_replacement_options via MCP Protocol
                        check_call = await session.call_tool(
                            "check_replacement_options",
                            {
                                "order_id": "ORD-1001",
                                "customer_deadline": "2026-10-22T18:00:00",
                                "current_time": "2026-10-20T10:00:00",
                            },
                        )
                        check_payload = json.loads(check_call.content[0].text)
                        assert check_payload["status"] == "SUCCESS"
                        assert check_payload["meets_any_option"] is True

                        # 5. Call confirm_resolution without agreement -> rejected
                        no_agree_call = await session.call_tool(
                            "confirm_resolution",
                            {
                                "order_id": "ORD-1001",
                                "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
                                "customer_agreed": False,
                                "idempotency_key": "MCP-HTTP-TEST-001",
                            },
                        )
                        no_agree_payload = json.loads(no_agree_call.content[0].text)
                        assert no_agree_payload["status"] == "CONFIRMATION_REQUIRED"

                        # 6. Call confirm_resolution with agreement -> confirmed
                        confirm_call = await session.call_tool(
                            "confirm_resolution",
                            {
                                "order_id": "ORD-1001",
                                "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
                                "customer_agreed": True,
                                "idempotency_key": "MCP-HTTP-TEST-001",
                            },
                        )
                        confirm_payload = json.loads(confirm_call.content[0].text)
                        assert confirm_payload["status"] == "CONFIRMED"
                        assert confirm_payload["idempotent_replay"] is False

                        # 7. Call confirm_resolution AGAIN (Idempotency replay test)
                        retry_call = await session.call_tool(
                            "confirm_resolution",
                            {
                                "order_id": "ORD-1001",
                                "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
                                "customer_agreed": True,
                                "idempotency_key": "MCP-HTTP-TEST-001",
                            },
                        )
                        retry_payload = json.loads(retry_call.content[0].text)
                        assert retry_payload["status"] == "ALREADY_CONFIRMED"
                        assert retry_payload["idempotent_replay"] is True

                        # 8. Call get_case_history via MCP Protocol
                        history_call = await session.call_tool("get_case_history", {"order_id": "ORD-1001"})
                        history_payload = json.loads(history_call.content[0].text)
                        assert history_payload["status"] == "SUCCESS"
                        assert history_payload["event_count"] >= 3
