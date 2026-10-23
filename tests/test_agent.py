"""
Tests for Doorstep Resolve Bounded Agent Orchestrator & Mock Provider (Milestone B).

Validates:
1. Invoking get_order through MCP protocol.
2. Invoking check_replacement_options through MCP protocol.
3. Multi-tool workflow (get_order -> check_replacement_options -> get_case_history).
4. Unknown tool handling and malformed arguments.
5. Tool errors and maximum-iteration (5) enforcement.
6. Confirmation tool exclusion:
   - confirm_resolution is never exposed in the tool list passed to providers.
   - If a provider attempts to invoke confirm_resolution, the orchestrator blocks it
     with a SECURITY_VIOLATION and refuses to execute it.
7. Proper client/session cleanup on both success and failure.
8. Clear identification of DeterministicMockProvider as a test component (is_mock=True).
9. Configurable MCP server URL and clean ASGI in-process test lifecycle.
"""

import pytest
import anyio
import httpx2

from doorstep_resolve.db import Database
from doorstep_resolve.server import create_mcp_server
from doorstep_resolve.agent import (
    DoorstepAgentOrchestrator,
    DeterministicMockProvider,
    AgentOrchestratorResult,
    ALLOWED_READ_ONLY_TOOLS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MCP_SERVER_URL,
    ToolCall,
    LLMStepResult,
    LLMProvider,
)


@pytest.fixture
def test_db(tmp_path):
    """Provides an isolated SQLite database populated with default scenario data."""
    db_file = tmp_path / "test_doorstep_agent.db"
    return Database(db_path=str(db_file))


@pytest.fixture
def mcp_server_and_transport(test_db):
    """
    Sets up an in-process MCP server with ASGITransport for isolated client/orchestrator testing.
    """
    server = create_mcp_server(db=test_db)
    app = server.streamable_http_app()
    transport = httpx2.ASGITransport(app=app)
    return server, transport


@pytest.fixture(autouse=True)
def force_mock_provider(monkeypatch):
    """Ensure test_agent runs with the deterministic mock provider regardless of local .env."""
    monkeypatch.setenv("DOORSTEP_LLM_PROVIDER", "mock")


class TestAgentOrchestrator:
    """Milestone B verification suite for the Bounded Agent Orchestrator."""

    @pytest.mark.anyio
    async def test_agent_invokes_get_order_through_mcp(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run("What is the status of order ORD-1001?")

                assert isinstance(result, AgentOrchestratorResult)
                assert result.is_success is True
                assert result.iterations >= 1
                assert len(result.tool_traces) == 1

                trace = result.tool_traces[0]
                assert trace.tool == "get_order"
                assert trace.arguments == {"order_id": "ORD-1001"}
                assert trace.status == "SUCCESS"
                assert trace.response["order"]["order_id"] == "ORD-1001"
                assert trace.response["order"]["item_id"] == "SKU-HEADPHONES-PRO"
                assert trace.duration_ms >= 1

                assert "ORD-1001" in result.assistant_message
                assert "Noise Cancelling Wireless Headphones" in result.assistant_message
                assert result.is_mock is True
                assert result.provider_name == "deterministic-mock-test-provider"

    @pytest.mark.anyio
    async def test_agent_invokes_check_replacement_options_through_mcp(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run(
                    "Check replacement options for ORD-1001 with deadline 2026-10-22T18:00:00"
                )

                assert result.is_success is True
                assert len(result.tool_traces) == 2

                tool_names = [t.tool for t in result.tool_traces]
                assert tool_names == ["get_order", "check_replacement_options"]

                check_trace = result.tool_traces[1]
                assert check_trace.tool == "check_replacement_options"
                assert check_trace.status == "SUCCESS"
                assert check_trace.response["meets_any_option"] is True

                # Check evidence gathering
                assert len(result.evidence) >= 1
                assert any("Promise safe" in ev for ev in result.evidence)
                assert result.resolution_data is not None
                assert result.resolution_data["order_id"] == "ORD-1001"

                assert "Replacement feasible" in result.assistant_message
                assert "WH-EAST-1" in result.assistant_message

    @pytest.mark.anyio
    async def test_agent_multi_tool_workflow_including_case_history(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run(
                    "Investigate order ORD-1001: check if replacement is possible for deadline 2026-10-22T18:00:00 and retrieve case history timeline"
                )

                assert result.is_success is True
                assert len(result.tool_traces) == 3

                tool_names = [t.tool for t in result.tool_traces]
                assert tool_names == ["get_order", "check_replacement_options", "get_case_history"]

                hist_trace = result.tool_traces[2]
                assert hist_trace.tool == "get_case_history"
                assert hist_trace.status == "SUCCESS"
                assert hist_trace.response["event_count"] >= 1

                assert "audit timeline" in result.assistant_message.lower()

    @pytest.mark.anyio
    async def test_agent_handles_unknown_tool_gracefully(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run("Test TRIGGER_UNKNOWN_TOOL behavior")

                assert len(result.tool_traces) == 1
                trace = result.tool_traces[0]
                assert trace.tool == "unknown_mock_tool"
                assert trace.status == "ERROR"
                assert trace.is_error is True
                assert "unauthorized tool" in trace.response["error"].lower()

                # Agent loop still finishes gracefully with an explanation
                assert result.is_success is True
                assert "gracefully" in result.assistant_message.lower()

    @pytest.mark.anyio
    async def test_agent_handles_malformed_arguments(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run("Test TRIGGER_MALFORMED_ARGS behavior")

                assert len(result.tool_traces) == 1
                trace = result.tool_traces[0]
                assert trace.tool == "get_order"
                assert trace.status == "ERROR"
                assert trace.is_error is True

                assert result.is_success is True
                assert "invalid argument" in result.assistant_message.lower()

    @pytest.mark.anyio
    async def test_maximum_iteration_enforcement(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                    max_iterations=5,
                )

                result = await orchestrator.run("Run TRIGGER_INFINITE_LOOP test")

                assert result.is_success is False
                assert result.iterations == 5
                assert len(result.tool_traces) == 5
                assert "maximum tool iterations" in result.error.lower()
                assert "maximum reasoning iterations" in result.assistant_message.lower()

    @pytest.mark.anyio
    async def test_confirmation_tool_not_exposed_in_tool_list(self, mcp_server_and_transport):
        """
        Critical Safety Guarantee 1:
        confirm_resolution is never exposed in the tool list provided to the model.
        """
        server, transport = mcp_server_and_transport

        # Mock provider that captures the tools passed to it
        class ToolSpyProvider(LLMProvider):
            def __init__(self):
                self.captured_tools = []

            @property
            def provider_name(self) -> str:
                return "tool-spy-provider"

            @property
            def is_mock(self) -> bool:
                return True

            async def chat_step(self, messages, tools):
                self.captured_tools = tools
                return LLMStepResult(assistant_message="Tools captured", finish_reason="stop")

        spy_provider = ToolSpyProvider()

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    provider=spy_provider,
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                await orchestrator.run("Inspect registered tools")

                # Exposed tools contain only allowed read-only tools
                exposed_tool_names = [t["name"] for t in spy_provider.captured_tools]
                assert "confirm_resolution" not in exposed_tool_names, (
                    "confirm_resolution MUST NOT be exposed to the conversational agent!"
                )
                for name in exposed_tool_names:
                    assert name in ALLOWED_READ_ONLY_TOOLS

    @pytest.mark.anyio
    async def test_confirmation_tool_execution_attempt_blocked(self, mcp_server_and_transport):
        """
        Critical Safety Guarantee 2:
        If a provider attempts to call confirm_resolution, orchestrator blocks it
        with a SECURITY_VIOLATION and refuses to invoke the MCP server.
        """
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                blocked_result = await orchestrator.run("Execute TRIGGER_CONFIRMATION_ATTEMPT")

                assert blocked_result.is_success is False
                assert "Security Violation" in blocked_result.error
                assert "confirm_resolution" in blocked_result.error
                assert len(blocked_result.tool_traces) == 1
                assert blocked_result.tool_traces[0].status == "SECURITY_VIOLATION"
                assert blocked_result.tool_traces[0].is_error is True

    @pytest.mark.anyio
    async def test_session_cleanup_after_completion_and_failure(self, mcp_server_and_transport):
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                # Successful run
                res_success = await orchestrator.run("Order ORD-1001 status")
                assert res_success.is_success is True

                # Failed run (iteration bound)
                res_fail = await orchestrator.run("Run TRIGGER_INFINITE_LOOP test")
                assert res_fail.is_success is False

                # Verify subsequent query still executes cleanly without socket or session leak
                res_reconnect = await orchestrator.run("Order ORD-1002 status")
                assert res_reconnect.is_success is True
                assert res_reconnect.tool_traces[0].arguments["order_id"] == "ORD-1002"

    @pytest.mark.anyio
    async def test_agent_scenario_5_expedited_rescue_ranks_air_as_feasible_and_ground_as_late(self, mcp_server_and_transport):
        """
        Regression test: ORD-1005 'Expedited Rescue (Air Beats Ground)'.
        Verifies that under simulation context (deadline Oct 22 12:00 PM, current time Oct 20 16:00),
        Expedited Air meets deadline (ETA Oct 22 03:00 AM) and is ranked #1 (feasible recommendation),
        while Standard Ground misses deadline (ETA Oct 23 15:00) and is ranked #2 (late fallback).
        """
        server, transport = mcp_server_and_transport

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run(
                    "Evaluate replacement options for order ORD-1005 with deadline 2026-10-22T12:00:00",
                    context={
                        "order_id": "ORD-1005",
                        "customer_deadline": "2026-10-22T12:00:00",
                        "current_time": "2026-10-20T16:00:00",
                    },
                )

                assert result.is_success is True
                assert result.resolution_data is not None
                res_data = result.resolution_data

                assert res_data["meets_any_option"] is True
                assert res_data["options_count"] == 2

                # Air option must meet the deadline and be ranked #1
                air_opt = res_data["options"][0]
                assert air_opt["action_type"] == "REPLACEMENT_EXPEDITED"
                assert air_opt["shipping_speed"] == "Expedited Air"
                assert air_opt["meets_deadline"] is True
                assert air_opt["is_eligible"] is True
                assert air_opt["rank"] == 1
                assert air_opt["cost"] == 14.99
                assert air_opt["estimated_arrival"] == "2026-10-22T03:00:00"

                # Ground option must miss the deadline and be ranked #2
                ground_opt = res_data["options"][1]
                assert ground_opt["action_type"] == "REPLACEMENT_STANDARD"
                assert ground_opt["shipping_speed"] == "Standard Ground"
                assert ground_opt["meets_deadline"] is False
                assert ground_opt["is_eligible"] is True
                assert ground_opt["rank"] == 2
                assert ground_opt["cost"] == 0.0
                assert ground_opt["estimated_arrival"] == "2026-10-23T15:00:00"

                # Top option is Air
                assert res_data["top_option"]["action_type"] == "REPLACEMENT_EXPEDITED"
                assert res_data["top_option"]["meets_deadline"] is True

    def test_mock_provider_is_clearly_identified_as_test_component(self):
        """Validates that the mock provider cannot be mistaken for a genuine LLM."""
        provider = DeterministicMockProvider()
        assert provider.is_mock is True
        assert "mock" in provider.provider_name.lower()
        assert "test" in provider.provider_name.lower()

        # Orchestrator also reports mock status
        orchestrator = DoorstepAgentOrchestrator(provider=provider)
        assert orchestrator.provider.is_mock is True

    def test_configurable_server_url_defaults(self):
        """Validates configurable MCP server URL."""
        orchestrator_default = DoorstepAgentOrchestrator()
        assert orchestrator_default.server_url == DEFAULT_MCP_SERVER_URL
        assert orchestrator_default.max_iterations == DEFAULT_MAX_ITERATIONS

        custom_url = "http://10.0.0.5:9999/mcp"
        orchestrator_custom = DoorstepAgentOrchestrator(server_url=custom_url, max_iterations=3)
        assert orchestrator_custom.server_url == custom_url
        assert orchestrator_custom.max_iterations == 3
