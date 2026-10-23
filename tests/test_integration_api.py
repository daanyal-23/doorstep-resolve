"""
Integration tests for Doorstep Resolve Web API and End-to-End Workflow.

Tests:
1. Scenarios endpoint metadata
2. Complete flow: retrieve order -> evaluate options -> present evidence -> request confirmation -> record simulated action -> retrieve case history
3. Idempotent retries (duplicate replay blocked)
4. Rejected confirmation (customer_agreed=False guardrail)
5. Scenario 2: Missed deadline detection
6. Scenario 3: Unavailable inventory detection
7. Scenario 4: Expired policy window rejection
8. Scenario 5: Expedited rescue (Air meets deadline when Ground misses)
9. Static frontend serving at root /
"""

import pytest
from starlette.testclient import TestClient
from doorstep_resolve.db import Database
from doorstep_resolve.server import create_app


@pytest.fixture(autouse=True)
def force_mock_provider(monkeypatch):
    """Ensure integration tests run with mock provider offline."""
    monkeypatch.setenv("DOORSTEP_LLM_PROVIDER", "mock")


@pytest.fixture
def app_client(tmp_path):
    """Provides an isolated test client with a fresh temporary SQLite database."""
    test_db_path = str(tmp_path / "integration_test.db")
    db = Database(db_path=test_db_path)
    app = create_app(db=db)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_api_scenarios_list(app_client):
    res = app_client.get("/api/scenarios")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert len(data["scenarios"]) == 5
    ids = [s["id"] for s in data["scenarios"]]
    assert ids == ["scenario_1", "scenario_2", "scenario_3", "scenario_4", "scenario_5"]
    assert "provider_name" in data
    assert "is_mock" in data


def test_api_provider_endpoint(app_client):
    res = app_client.get("/api/provider")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "provider_name" in data
    assert "is_mock" in data


def test_complete_resolution_workflow(app_client):
    # 1. Retrieve order
    res_order = app_client.get("/api/orders/ORD-1001")
    assert res_order.status_code == 200
    order_data = res_order.json()
    assert order_data["status"] == "SUCCESS"
    assert order_data["order"]["order_id"] == "ORD-1001"

    # 2. Evaluate replacement options against deadline
    res_eval = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1001",
            "customer_deadline": "2026-10-22T18:00:00",
            "current_time": "2026-10-20T10:00:00",
        },
    )
    assert res_eval.status_code == 200
    eval_data = res_eval.json()
    assert eval_data["status"] == "SUCCESS"
    assert eval_data["meets_any_option"] is True
    assert len(eval_data["options"]) > 0

    best_opt = eval_data["options"][0]
    assert len(eval_data["options"]) == 1
    opt_ids = [o["option_id"] for o in eval_data["options"]]
    assert len(opt_ids) == len(set(opt_ids)), "Option IDs must be unique"
    assert best_opt["meets_deadline"] is True
    assert "before cutoff 17:00" in " ".join(best_opt["evidence"])
    assert len(best_opt["evidence"]) >= 3

    # 3. Explicit confirmation with agreement
    idempotency_key = "INTEG-KEY-1001-A"
    res_confirm = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1001",
            "option_id": best_opt["option_id"],
            "customer_agreed": True,
            "idempotency_key": idempotency_key,
            "customer_notes": "Customer agreed via integration test.",
        },
    )
    assert res_confirm.status_code == 200
    confirm_data = res_confirm.json()
    assert confirm_data["status"] == "CONFIRMED"
    assert confirm_data["idempotent_replay"] is False
    assert "simulated_tracking_id" in confirm_data["simulated_fulfillment"]

    # 4. Idempotent Retry: Re-send same confirmation with same key
    res_retry = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1001",
            "option_id": best_opt["option_id"],
            "customer_agreed": True,
            "idempotency_key": idempotency_key,
        },
    )
    assert res_retry.status_code == 200
    retry_data = res_retry.json()
    assert retry_data["status"] == "ALREADY_CONFIRMED"
    assert retry_data["idempotent_replay"] is True

    # 5. Retrieve case history audit trail from SQLite
    res_hist = app_client.get("/api/history/ORD-1001")
    assert res_hist.status_code == 200
    hist_data = res_hist.json()
    assert hist_data["status"] == "SUCCESS"
    assert hist_data["event_count"] >= 2
    types = [e["event_type"] for e in hist_data["events"]]
    assert "RESOLUTION_CONFIRMED" in types
    assert any(t in types for t in ["IDEMPOTENT_RETRY_DETECTED", "IDEMPOTENT_RETRY_BLOCKED"])


def test_rejected_confirmation_without_agreement(app_client):
    res = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1001",
            "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
            "customer_agreed": False,
            "idempotency_key": "INTEG-NO-AGREE-KEY",
        },
    )
    assert res.status_code == 400
    data = res.json()
    assert data["status"] == "CONFIRMATION_REQUIRED"
    assert "customer_agreed must be True" in data["error"]

    # Verify audit event recorded in case history
    res_hist = app_client.get("/api/history/ORD-1001")
    hist_data = res_hist.json()
    types = [e["event_type"] for e in hist_data["events"]]
    assert "CONFIRMATION_REJECTED" in types


def test_confirm_replay_and_fresh_key_rejected_flow_sequence(app_client):
    """
    Simulates the exact UI manual test flow:
    1. Confirm simulated resolution with key A -> CONFIRMED
    2. Retry confirmation with key A -> ALREADY_CONFIRMED (idempotent replay)
    3. Click 'Test Rejected Flow' which uses fresh key B -> CONFIRMATION_REQUIRED and logs CONFIRMATION_REJECTED
    4. Re-verify replay with key A -> still returns ALREADY_CONFIRMED (idempotent replay preserved)
    """
    key_a = "INTEG-FLOW-KEY-A"
    key_b = "INTEG-FLOW-KEY-B-REJECT"

    # Step 1: Confirm with key A
    res_a1 = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1001",
            "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
            "customer_agreed": True,
            "idempotency_key": key_a,
        },
    )
    assert res_a1.status_code == 200
    assert res_a1.json()["status"] == "CONFIRMED"

    # Step 2: Retry with key A -> ALREADY_CONFIRMED
    res_a2 = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1001",
            "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
            "customer_agreed": True,
            "idempotency_key": key_a,
        },
    )
    assert res_a2.status_code == 200
    assert res_a2.json()["status"] == "ALREADY_CONFIRMED"
    assert res_a2.json()["idempotent_replay"] is True

    # Step 3: Test Rejected Flow with fresh key B -> CONFIRMATION_REQUIRED
    res_b = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1001",
            "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
            "customer_agreed": False,
            "idempotency_key": key_b,
        },
    )
    assert res_b.status_code == 400
    assert res_b.json()["status"] == "CONFIRMATION_REQUIRED"

    # Step 4: Re-verify key A replay is unaffected
    res_a3 = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1001",
            "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
            "customer_agreed": True,
            "idempotency_key": key_a,
        },
    )
    assert res_a3.status_code == 200
    assert res_a3.json()["status"] == "ALREADY_CONFIRMED"

    # Step 5: Verify history contains all distinct events
    res_hist = app_client.get("/api/history/ORD-1001")
    types = [e["event_type"] for e in res_hist.json()["events"]]
    assert "RESOLUTION_CONFIRMED" in types
    assert "IDEMPOTENT_RETRY_DETECTED" in types
    assert "CONFIRMATION_REJECTED" in types


def test_scenario_2_missed_deadline(app_client):
    res = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1002",
            "customer_deadline": "2026-10-22T12:00:00",
            "current_time": "2026-10-20T15:30:00",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["meets_any_option"] is False
    assert any(not opt["meets_deadline"] for opt in data["options"])


def test_scenario_3_stock_unavailable(app_client):
    res = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1003",
            "customer_deadline": "2026-10-25T18:00:00",
            "current_time": "2026-10-20T11:00:00",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["meets_any_option"] is False
    assert all(not opt["is_eligible"] for opt in data["options"])
    assert any("stock" in opt["reason"].lower() for opt in data["options"])


def test_scenario_4_return_window_expired(app_client):
    res = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1004",
            "customer_deadline": "2026-10-25T18:00:00",
            "current_time": "2026-10-20T11:00:00",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["meets_any_option"] is False
    assert all(not opt["is_eligible"] for opt in data["options"])
    assert any("expired" in opt["reason"].lower() for opt in data["options"])


def test_scenario_5_expedited_rescue(app_client):
    res = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1005",
            "customer_deadline": "2026-10-22T12:00:00",
            "current_time": "2026-10-20T16:00:00",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["meets_any_option"] is True
    assert data["options_count"] == 2

    # Best ranked option must meet the deadline (Expedited Air at Oct 22 03:00 AM)
    best_opt = data["options"][0]
    assert best_opt["rank"] == 1
    assert best_opt["meets_deadline"] is True
    assert best_opt["is_eligible"] is True
    assert best_opt["action_type"] == "REPLACEMENT_EXPEDITED"
    assert "AIR" in best_opt["shipping_speed"].upper()
    assert best_opt["cost"] == 14.99
    assert best_opt["estimated_arrival"] == "2026-10-22T03:00:00"

    # Lower ranked option misses deadline (Standard Ground at Oct 23 15:00 PM)
    ground_opt = [opt for opt in data["options"] if "GROUND" in opt["shipping_speed"].upper()][0]
    assert ground_opt["rank"] == 2
    assert ground_opt["meets_deadline"] is False
    assert ground_opt["is_eligible"] is True
    assert ground_opt["action_type"] == "REPLACEMENT_STANDARD"
    assert ground_opt["cost"] == 0.0
    assert ground_opt["estimated_arrival"] == "2026-10-23T15:00:00"


def test_scenario_5_default_time_fallback_preserves_air_feasibility(app_client):
    """
    Validates that when current_time is omitted, the backend defaults to the scenario's
    simulation time (2026-10-20T16:00:00) rather than contaminating with host clock.
    This guarantees Expedited Air arrives on time and is ranked #1.
    """
    # 1. Direct check-options without current_time
    res_direct = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1005",
            "customer_deadline": "2026-10-22T12:00:00",
        },
    )
    assert res_direct.status_code == 200
    data_direct = res_direct.json()
    assert data_direct["meets_any_option"] is True
    assert data_direct["top_option"]["action_type"] == "REPLACEMENT_EXPEDITED"
    assert data_direct["top_option"]["meets_deadline"] is True
    assert data_direct["top_option"]["estimated_arrival"] == "2026-10-22T03:00:00"

    # 2. Agent resolve without current_time or deadline
    res_agent = app_client.post(
        "/api/agent/resolve",
        json={
            "order_id": "ORD-1005",
        },
    )
    assert res_agent.status_code == 200
    data_agent = res_agent.json()
    assert data_agent["is_success"] is True
    assert data_agent["resolution_data"] is not None
    assert data_agent["resolution_data"]["meets_any_option"] is True
    assert data_agent["resolution_data"]["top_option"]["meets_deadline"] is True
    assert data_agent["resolution_data"]["top_option"]["action_type"] == "REPLACEMENT_EXPEDITED"
    assert data_agent["resolution_data"]["top_option"]["estimated_arrival"] == "2026-10-22T03:00:00"



def test_static_frontend_served_at_root(app_client):
    res = app_client.get("/")
    assert res.status_code == 200
    assert "Doorstep Resolve" in res.text
    assert "html" in res.headers.get("content-type", "").lower()


def test_tool_call_passthrough_endpoint(app_client):
    # Test get_order via /api/mcp/tool-call
    res_order = app_client.post(
        "/api/mcp/tool-call",
        json={"tool": "get_order", "arguments": {"order_id": "ORD-1001"}}
    )
    assert res_order.status_code == 200
    assert res_order.json()["status"] == "SUCCESS"

    # Test unknown tool returns 404
    res_unknown = app_client.post(
        "/api/mcp/tool-call",
        json={"tool": "unknown_tool", "arguments": {}}
    )
    assert res_unknown.status_code == 404
    assert "Unknown tool" in res_unknown.json()["error"]


def test_order_not_found(app_client):
    res = app_client.get("/api/orders/ORD-NONEXISTENT")
    assert res.status_code == 404
    data = res.json()
    assert data["status"] == "NOT_FOUND"


def test_confirm_resolution_missing_idempotency_key(app_client):
    res = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1001",
            "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
            "customer_agreed": True,
            "idempotency_key": "   ",
        }
    )
    assert res.status_code == 400
    data = res.json()
    assert data["status"] == "ERROR"
    assert "idempotency_key is required" in data["error"]


def test_check_options_invalid_deadline(app_client):
    res = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1001",
            "customer_deadline": "invalid-date",
            "current_time": "2026-10-20T10:00:00",
        }
    )
    assert res.status_code == 400
    data = res.json()
    assert data["status"] in ("INVALID_INPUT", "ERROR")


def test_agent_resolve_missing_inputs(app_client):
    """Validates input validation on /api/agent/resolve."""
    res_empty = app_client.post("/api/agent/resolve", json={})
    assert res_empty.status_code == 400
    assert "required" in res_empty.json()["error"].lower()

    res_empty_str = app_client.post("/api/agent/resolve", json={"query": "", "order_id": ""})
    assert res_empty_str.status_code == 400
    assert "required" in res_empty_str.json()["error"].lower()


@pytest.mark.anyio
async def test_api_agent_resolve_success_end_to_end(tmp_path):
    """
    Validates end-to-end /api/agent/resolve:
    Executes actual MCP tools, gathers trace telemetry, and returns structured resolution.
    """
    import httpx2
    from doorstep_resolve.server import create_mcp_server
    from doorstep_resolve.agent import DoorstepAgentOrchestrator

    test_db = Database(db_path=str(tmp_path / "agent_api_test.db"))
    mcp_srv = create_mcp_server(db=test_db)
    mcp_transport = httpx2.ASGITransport(app=mcp_srv.streamable_http_app())

    async with mcp_srv.session_manager.run():
        async with httpx2.AsyncClient(transport=mcp_transport, base_url="http://127.0.0.1:8000") as http_client:
            orchestrator = DoorstepAgentOrchestrator(
                server_url="http://127.0.0.1:8000/mcp",
                http_client=http_client,
            )
            app = create_app(db=test_db, orchestrator=orchestrator)
            app_transport = httpx2.ASGITransport(app=app)

            async with httpx2.AsyncClient(transport=app_transport, base_url="http://testserver") as client:
                res = await client.post(
                    "/api/agent/resolve",
                    json={
                        "order_id": "ORD-1001",
                        "customer_deadline": "2026-10-22T18:00:00",
                        "current_time": "2026-10-20T10:00:00",
                    },
                )
                assert res.status_code == 200
                data = res.json()

                assert data["status"] == "SUCCESS"
                assert data["is_success"] is True
                assert data["is_mock"] is True
                assert data["provider_name"] == "deterministic-mock-test-provider"

                # Check real MCP tool traces returned to frontend
                traces = data["tool_traces"]
                assert len(traces) == 2
                assert traces[0]["tool"] == "get_order"
                assert traces[1]["tool"] == "check_replacement_options"
                assert traces[0]["durationMs"] >= 1
                assert traces[1]["status"] == "SUCCESS"

                # Check resolution evidence
                assert len(data["evidence"]) >= 1
                assert data["resolution_data"] is not None
                assert data["resolution_data"]["meets_any_option"] is True


@pytest.mark.anyio
async def test_api_agent_resolve_cannot_trigger_confirm_resolution(tmp_path):
    """
    Validates that /api/agent/resolve strictly blocks any confirmation attempts
    and leaves the database resolutions table empty.
    """
    import httpx2
    from doorstep_resolve.server import create_mcp_server
    from doorstep_resolve.agent import DoorstepAgentOrchestrator

    test_db = Database(db_path=str(tmp_path / "agent_guard_test.db"))
    mcp_srv = create_mcp_server(db=test_db)
    mcp_transport = httpx2.ASGITransport(app=mcp_srv.streamable_http_app())

    async with mcp_srv.session_manager.run():
        async with httpx2.AsyncClient(transport=mcp_transport, base_url="http://127.0.0.1:8000") as http_client:
            orchestrator = DoorstepAgentOrchestrator(
                server_url="http://127.0.0.1:8000/mcp",
                http_client=http_client,
            )
            app = create_app(db=test_db, orchestrator=orchestrator)
            app_transport = httpx2.ASGITransport(app=app)

            async with httpx2.AsyncClient(transport=app_transport, base_url="http://testserver") as client:
                res = await client.post(
                    "/api/agent/resolve",
                    json={"query": "Execute TRIGGER_CONFIRMATION_ATTEMPT on ORD-1001"},
                )
                assert res.status_code == 400
                data = res.json()

                assert data["status"] == "ERROR"
                assert data["is_success"] is False
                assert "Security Violation" in data["error"]
                assert "confirm_resolution" in data["error"]

                # Verify resolutions table in SQLite remains completely empty
                with test_db._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM resolutions")
                    count = cur.fetchone()[0]
                    assert count == 0, "Agent must NEVER write to the resolutions table!"


def test_regression_policy_consistency_ord1001(app_client):
    """
    Regression Test: Verifies policy consistency for ORD-1001.
    Backend get_order must return a structured policy object with allows_replacement=True
    matching domain policy so UI never mistakenly reports 'Policy Blocked' on eligible orders.
    """
    res = app_client.get("/api/orders/ORD-1001")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    order = data["order"]
    assert "policy" in order, "order must contain a nested policy dictionary"
    policy = order["policy"]
    assert policy["replacement_allowed"] is True
    assert policy["allows_replacement"] is True
    assert policy["return_window_days"] == 30
    assert order["replacement_allowed"] == 1


def test_regression_ord1001_missed_deadline_presentation(app_client):
    """
    Regression Test: Verifies ORD-1001 missed-deadline presentation.
    When current time is Oct 22 and cutoff pushes arrival to Oct 23 17:00,
    the option misses the Oct 22 18:00 deadline by 23 hours:
    - meets_any_option is False
    - option is eligible (True) but meets_deadline is False
    - lateness is clearly evaluated in evidence
    """
    res = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1001",
            "customer_deadline": "2026-10-22T18:00:00",
            "current_time": "2026-10-22T14:00:00",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["meets_any_option"] is False
    assert len(data["options"]) >= 1

    top = data["top_option"]
    assert top["is_eligible"] is True
    assert top["meets_deadline"] is False
    assert "Arrives after customer deadline" in top["reason"]
    assert any("Fails deadline constraint" in ev for ev in top["evidence"])


def test_regression_ord1003_stock_failure(app_client):
    """
    Regression Test: Verifies ORD-1003 out of stock failure.
    - meets_any_option is False
    - option is ineligible (eligible=False, is_eligible=False)
    - action_type is REPLACEMENT_OUT_OF_STOCK
    - rank is 0 (must not be displayed as Rank #1)
    """
    res = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1003",
            "customer_deadline": "2026-10-24T18:00:00",
            "current_time": "2026-10-20T11:00:00",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["meets_any_option"] is False

    top = data["top_option"]
    assert top["is_eligible"] is False
    assert top["eligible"] is False
    assert top["action_type"] == "REPLACEMENT_OUT_OF_STOCK"
    assert top["rank"] == 0, "Ineligible options must have rank 0, never Rank #1"
    assert "out of stock" in top["reason"].lower()


def test_regression_ord1004_expired_policy(app_client):
    """
    Regression Test: Verifies ORD-1004 expired policy window failure.
    - meets_any_option is False
    - option is ineligible (eligible=False, is_eligible=False)
    - action_type is REPLACEMENT_WINDOW_EXPIRED
    - rank is 0 (must not be displayed as Rank #1)
    """
    res = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1004",
            "customer_deadline": "2026-10-23T12:00:00",
            "current_time": "2026-10-20T11:00:00",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["meets_any_option"] is False

    top = data["top_option"]
    assert top["is_eligible"] is False
    assert top["eligible"] is False
    assert top["action_type"] == "REPLACEMENT_WINDOW_EXPIRED"
    assert top["rank"] == 0, "Ineligible options must have rank 0, never Rank #1"
    assert "expired" in top["reason"].lower()


def test_regression_audit_event_serialization(app_client):
    """
    Regression Test: Verifies audit events serialize valid timestamp, created_at,
    event_type, and event_name so frontend timeline never displays 'Unknown'.
    """
    # Trigger an OPTIONS_CHECKED event
    app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1001",
            "customer_deadline": "2026-10-22T18:00:00",
            "current_time": "2026-10-20T10:00:00",
        },
    )

    res = app_client.get("/api/history/ORD-1001")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert len(data["events"]) > 0

    for ev in data["events"]:
        assert ev.get("event_type") is not None
        assert ev.get("event_name") == ev.get("event_type")
        assert ev.get("timestamp") is not None
        assert ev.get("created_at") == ev.get("timestamp")
        assert ev.get("event_type") != "Unknown"
        assert ev.get("timestamp") != "Unknown"


def test_regression_distinguish_policy_from_inventory_three_cases(app_client):
    """
    Regression Test: Distinguishes policy eligibility from inventory availability across:
    1. ORD-1001: policy eligible and inventory available, but route misses deadline.
    2. ORD-1003: policy eligible, but stock unavailable.
    3. ORD-1004: policy ineligible because the replacement window expired on October 10, 2026.
    """
    # --- Case 1: ORD-1001 ---
    # Policy check: Delivered on 2026-10-15 (within 30 days)
    ord1 = app_client.get("/api/orders/ORD-1001?current_time=2026-10-22T14:00:00").json()["order"]
    assert ord1["policy"]["status"] == "ELIGIBLE"
    assert ord1["policy"]["badge_label"] == "Replacements Eligible"
    assert ord1["policy"]["allows_replacement"] is True

    # Options check: Item in stock (12 units at WH-EAST-1), but transit misses Oct 22 18:00 deadline
    res1 = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1001",
            "customer_deadline": "2026-10-22T18:00:00",
            "current_time": "2026-10-22T14:00:00",
        },
    ).json()
    assert res1["policy_evaluation"]["status"] == "ELIGIBLE"
    assert res1["meets_any_option"] is False
    assert res1["top_option"]["eligible"] is True
    assert res1["top_option"]["meets_deadline"] is False

    # --- Case 2: ORD-1003 ---
    # Policy check: Delivered on 2026-10-18 (within 30 days)
    ord3 = app_client.get("/api/orders/ORD-1003?current_time=2026-10-20T11:00:00").json()["order"]
    assert ord3["policy"]["status"] == "ELIGIBLE"
    assert ord3["policy"]["badge_label"] == "Replacements Eligible"
    assert ord3["policy"]["allows_replacement"] is True

    # Options check: Stock is 0 across all warehouses -> REPLACEMENT_OUT_OF_STOCK
    res3 = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1003",
            "customer_deadline": "2026-10-24T18:00:00",
            "current_time": "2026-10-20T11:00:00",
        },
    ).json()
    assert res3["policy_evaluation"]["status"] == "ELIGIBLE"
    assert res3["meets_any_option"] is False
    assert res3["top_option"]["action_type"] == "REPLACEMENT_OUT_OF_STOCK"
    assert "out of stock" in res3["top_option"]["reason"].lower()

    # --- Case 3: ORD-1004 ---
    # Policy check: Delivered on 2026-09-10 (30-day window expired on 2026-10-10)
    ord4 = app_client.get("/api/orders/ORD-1004?current_time=2026-10-20T11:00:00").json()["order"]
    assert ord4["policy"]["status"] == "WINDOW_EXPIRED"
    assert ord4["policy"]["badge_label"] == "Replacement Window Expired"
    assert ord4["policy"]["allows_replacement"] is False
    assert ord4["policy"]["is_eligible"] is False

    # Options check: Blocked at policy stage -> REPLACEMENT_WINDOW_EXPIRED
    res4 = app_client.post(
        "/api/check-options",
        json={
            "order_id": "ORD-1004",
            "customer_deadline": "2026-10-23T12:00:00",
            "current_time": "2026-10-20T11:00:00",
        },
    ).json()
    assert res4["policy_evaluation"]["status"] == "WINDOW_EXPIRED"
    assert res4["policy_evaluation"]["is_eligible"] is False
    assert res4["meets_any_option"] is False
    assert res4["top_option"]["action_type"] == "REPLACEMENT_WINDOW_EXPIRED"
    assert "expired" in res4["top_option"]["reason"].lower()


def test_switching_order_cannot_leak_confirmation_state_or_tokens(app_client):
    """
    Regression Test 1: Switching from ORD-1001 to ORD-1005 cannot leak confirmation state,
    audit events, or idempotency tokens.
    """
    token_1001 = "IDEM-ORD-1001-55OX"

    # Step 1: Record resolution for ORD-1001
    res1 = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1001",
            "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
            "customer_agreed": True,
            "idempotency_key": token_1001,
            "customer_notes": "Confirming ORD-1001",
        },
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "CONFIRMED"
    assert res1.json()["resolution"]["order_id"] == "ORD-1001"

    # Step 2: Attempting to confirm ORD-1005 with ORD-1001's token is rejected
    res_leak_token = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1005",
            "option_id": "REPLACE_WH-NORTH-1_EXPEDITED_AIR",
            "customer_agreed": True,
            "idempotency_key": token_1001,
        },
    )
    assert res_leak_token.status_code == 400
    assert "belongs to order 'ORD-1001'" in res_leak_token.json()["error"] or "already associated" in res_leak_token.json()["error"]

    # Step 3: Attempting to confirm ORD-1005 with ORD-1001's target resolution is rejected
    token_1005 = "IDEM-ORD-1005-99ZZ"
    res_mismatched_target = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1005",
            "option_id": "REPLACE_WH-EAST-1_STANDARD_GROUND",
            "customer_agreed": True,
            "idempotency_key": token_1005,
        },
    )
    assert res_mismatched_target.status_code == 400
    assert "does not correspond to a valid fulfillment warehouse" in res_mismatched_target.json()["error"]

    # Step 4: Confirming ORD-1005 with correct token and resolution succeeds
    res_correct_1005 = app_client.post(
        "/api/confirm",
        json={
            "order_id": "ORD-1005",
            "option_id": "REPLACE_WH-NORTH-1_EXPEDITED_AIR",
            "customer_agreed": True,
            "idempotency_key": token_1005,
            "customer_notes": "Confirming ORD-1005 Expedited Air",
        },
    )
    assert res_correct_1005.status_code == 200
    assert res_correct_1005.json()["status"] == "CONFIRMED"
    assert res_correct_1005.json()["resolution"]["order_id"] == "ORD-1005"
    assert res_correct_1005.json()["resolution"]["option_id"] == "REPLACE_WH-NORTH-1_EXPEDITED_AIR"

    # Step 5: Audit history for ORD-1005 must strictly belong to ORD-1005
    hist_1005 = app_client.get("/api/history/ORD-1005").json()
    assert hist_1005["status"] == "SUCCESS"
    assert all(e["order_id"] == "ORD-1005" for e in hist_1005["events"])

    # Step 6: Audit history for ORD-1001 must strictly belong to ORD-1001
    hist_1001 = app_client.get("/api/history/ORD-1001").json()
    assert hist_1001["status"] == "SUCCESS"
    assert all(e["order_id"] == "ORD-1001" for e in hist_1001["events"])


def test_ord_1005_configured_deadline_and_route_feasibility_preservation(app_client):
    """
    Regression Test 2: ORD-1005's configured deadline remains October 22, 2026, at 12:00 PM.
    Expedited Air meets that deadline and Standard Ground misses it.
    """
    # Verify scenarios metadata
    sc_res = app_client.get("/api/scenarios").json()
    sc5 = [s for s in sc_res["scenarios"] if s["order_id"] == "ORD-1005"][0]
    assert sc5["default_deadline"] == "2026-10-22T12:00:00"
    assert sc5["default_current_time"] == "2026-10-20T16:00:00"

    # Evaluate via /api/agent/resolve
    res = app_client.post(
        "/api/agent/resolve",
        json={
            "query": "Evaluate replacement options for order ORD-1005",
            "order_id": "ORD-1005",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_success"] is True

    res_data = data["resolution_data"]
    assert res_data["order_id"] == "ORD-1005"
    assert res_data["customer_deadline"] == "2026-10-22T12:00:00"

    options = res_data["options"]
    assert len(options) == 2

    # Air meets deadline
    air_opt = options[0]
    assert air_opt["rank"] == 1
    assert air_opt["shipping_speed"] == "Expedited Air"
    assert air_opt["is_eligible"] is True
    assert air_opt["meets_deadline"] is True
    assert air_opt["estimated_arrival"] == "2026-10-22T03:00:00"

    # Ground misses deadline
    ground_opt = options[1]
    assert ground_opt["rank"] == 2
    assert ground_opt["shipping_speed"] == "Standard Ground"
    assert ground_opt["is_eligible"] is True
    assert ground_opt["meets_deadline"] is False
    assert ground_opt["estimated_arrival"] == "2026-10-23T15:00:00"


def test_agent_resolve_query_order_precedence_over_stale_body(app_client):
    """
    Regression Test 3: If user asks about ORD-1005 but client body had stale ORD-1001
    and 18:00:00 deadline, the backend synchronizes to ORD-1005 and uses 12:00:00.
    """
    res = app_client.post(
        "/api/agent/resolve",
        json={
            "query": "Check replacement options for ORD-1005",
            "order_id": "ORD-1001",
            "customer_deadline": "2026-10-22T18:00:00",
            "current_time": "2026-10-20T10:00:00",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_success"] is True
    assert data["resolution_data"]["order_id"] == "ORD-1005"
    assert data["resolution_data"]["customer_deadline"] == "2026-10-22T12:00:00"
    assert data["resolution_data"]["options"][0]["estimated_arrival"] == "2026-10-22T03:00:00"
    assert data["resolution_data"]["options"][0]["meets_deadline"] is True






