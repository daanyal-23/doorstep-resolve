"""
Doorstep Resolve - Milestone D1: OpenAI API Provider Tests.

Covers:
- Provider selection via DOORSTEP_LLM_PROVIDER and missing credential handling.
- Mocked OpenAI responses and tool-call parsing (JSON arguments, stop reason).
- Single-tool and multi-tool workflows through real MCP protocol with OpenAI provider.
- Error handling: rate limits, insufficient credit / quota exhaustion, timeouts, auth errors, malformed responses.
- Security constraints: confirm_resolution blocking and iteration exhaustion under OpenAI provider.
- Preservation of authoritative backend evidence without hallucination or override.
- Offline execution without real API credentials or billable requests.
"""

import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from openai import (
    AuthenticationError,
    RateLimitError,
    APITimeoutError,
    NotFoundError,
    APIError,
)
import httpx2

from doorstep_resolve.agent import (
    OpenAIProvider,
    DeterministicMockProvider,
    get_default_provider,
    DoorstepAgentOrchestrator,
    ToolCall,
    LLMStepResult,
    AgentOrchestratorResult,
    OpenAIProviderError,
    OpenAIAuthError,
    OpenAIRateLimitError,
    OpenAIQuotaError,
    OpenAIModelError,
    OpenAITimeoutError,
    OpenAIConnectionError,
)
from pathlib import Path
from doorstep_resolve.config import load_project_env
from doorstep_resolve.db import Database
from doorstep_resolve.server import create_mcp_server, create_app


# Helper to build mock OpenAI chat completion responses
def make_mock_completion(
    content=None,
    tool_calls=None,
    finish_reason="stop",
):
    mock_choice = MagicMock()
    mock_choice.finish_reason = finish_reason
    mock_message = MagicMock()
    mock_message.content = content

    if tool_calls:
        formatted_calls = []
        for tc in tool_calls:
            mock_tc = MagicMock()
            mock_tc.id = tc.get("id", "call_mock_123")
            mock_tc.function = MagicMock()
            mock_tc.function.name = tc["name"]
            mock_tc.function.arguments = (
                json.dumps(tc["arguments"])
                if isinstance(tc["arguments"], dict)
                else tc["arguments"]
            )
            formatted_calls.append(mock_tc)
        mock_message.tool_calls = formatted_calls
    else:
        mock_message.tool_calls = None

    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


class TestOpenAIProviderSelectionAndConfig:
    """Verifies provider factory and configuration rules."""

    def test_provider_selection_defaults_to_mock(self, monkeypatch):
        monkeypatch.delenv("DOORSTEP_LLM_PROVIDER", raising=False)
        provider = get_default_provider()
        assert isinstance(provider, DeterministicMockProvider)
        assert provider.is_mock is True
        assert provider.provider_name == "deterministic-mock-test-provider"

    def test_provider_selection_explicit_mock(self, monkeypatch):
        monkeypatch.setenv("DOORSTEP_LLM_PROVIDER", "mock")
        provider = get_default_provider()
        assert isinstance(provider, DeterministicMockProvider)
        assert provider.is_mock is True

    def test_provider_selection_openai_missing_key_raises(self, monkeypatch):
        monkeypatch.setenv("DOORSTEP_LLM_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENAI_API_KEY environment variable is required"):
            get_default_provider()

    def test_provider_selection_openai_success(self, monkeypatch):
        monkeypatch.setenv("DOORSTEP_LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test-credentials-123")
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        provider = get_default_provider()
        assert isinstance(provider, OpenAIProvider)
        assert provider.is_mock is False
        assert provider.model == "gpt-6-luna"
        assert provider.provider_name == "openai:gpt-6-luna"

    def test_provider_selection_custom_model(self, monkeypatch):
        monkeypatch.setenv("DOORSTEP_LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test-credentials-123")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
        provider = get_default_provider()
        assert provider.model == "gpt-4o-mini"
        assert provider.provider_name == "openai:gpt-4o-mini"

    def test_provider_selection_unsupported_provider_fails(self, monkeypatch):
        monkeypatch.setenv("DOORSTEP_LLM_PROVIDER", "gemini")
        with pytest.raises(ValueError, match="Unsupported DOORSTEP_LLM_PROVIDER: 'gemini'"):
            get_default_provider()

        monkeypatch.setenv("DOORSTEP_LLM_PROVIDER", "ollama")
        with pytest.raises(ValueError, match="Unsupported DOORSTEP_LLM_PROVIDER: 'ollama'"):
            get_default_provider()


class TestEnvConfiguration:
    """Verifies that .env configuration is loaded automatically without overriding process env."""

    def test_env_file_loaded_when_process_env_missing(self, tmp_path, monkeypatch):
        # Ensure target variables are absent from process environment
        monkeypatch.delenv("DOORSTEP_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)

        test_env = tmp_path / ".env"
        test_env.write_text(
            "DOORSTEP_LLM_PROVIDER=openai\n"
            "OPENAI_API_KEY=sk-proj-test-from-dot-env\n"
            "OPENAI_MODEL=gpt-6-luna\n"
        )

        loaded = load_project_env(env_path=test_env, override=False)
        assert loaded is True
        assert os.environ.get("DOORSTEP_LLM_PROVIDER") == "openai"
        assert os.environ.get("OPENAI_API_KEY") == "sk-proj-test-from-dot-env"
        assert os.environ.get("OPENAI_MODEL") == "gpt-6-luna"

        provider = get_default_provider()
        assert isinstance(provider, OpenAIProvider)
        assert provider.model == "gpt-6-luna"
        assert provider.is_mock is False

    def test_explicit_process_env_takes_precedence_over_env_file(self, tmp_path, monkeypatch):
        # Set explicit process environment variables
        monkeypatch.setenv("DOORSTEP_LLM_PROVIDER", "mock")
        monkeypatch.setenv("OPENAI_MODEL", "custom-process-model")

        test_env = tmp_path / ".env"
        test_env.write_text(
            "DOORSTEP_LLM_PROVIDER=openai\n"
            "OPENAI_MODEL=env-file-model\n"
        )

        load_project_env(env_path=test_env, override=False)
        # Explicit process environment must NOT be overwritten by .env
        assert os.environ.get("DOORSTEP_LLM_PROVIDER") == "mock"
        assert os.environ.get("OPENAI_MODEL") == "custom-process-model"

        provider = get_default_provider()
        assert isinstance(provider, DeterministicMockProvider)
        assert provider.is_mock is True

    def test_missing_env_file_handled_gracefully(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist" / ".env"
        loaded = load_project_env(env_path=nonexistent)
        assert loaded is False


class TestOpenAIResponseAndToolCallParsing:
    """Tests tool-call parsing, stop conditions, and malformed responses."""

    @pytest.mark.anyio
    async def test_tool_call_parsing(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_mock_completion(
                tool_calls=[{
                    "id": "call_order_01",
                    "name": "get_order",
                    "arguments": {"order_id": "ORD-1001"},
                }],
                finish_reason="tool_calls",
            )
        )
        provider = OpenAIProvider(api_key="sk-test", client=mock_client)
        result = await provider.chat_step(
            messages=[{"role": "user", "content": "Look up ORD-1001"}],
            tools=[{"name": "get_order", "description": "Lookup order", "inputSchema": {}}],
        )

        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "get_order"
        assert result.tool_calls[0].arguments == {"order_id": "ORD-1001"}
        assert result.tool_calls[0].tool_call_id == "call_order_01"

    @pytest.mark.anyio
    async def test_final_stop_message_parsing(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_mock_completion(
                content="Replacement is feasible and arrives before deadline.",
                tool_calls=None,
                finish_reason="stop",
            )
        )
        provider = OpenAIProvider(api_key="sk-test", client=mock_client)
        result = await provider.chat_step(
            messages=[{"role": "user", "content": "Is replacement feasible?"}],
            tools=[],
        )

        assert result.finish_reason == "stop"
        assert not result.tool_calls
        assert "feasible and arrives" in result.assistant_message

    @pytest.mark.anyio
    async def test_malformed_tool_call_arguments_handled_safely(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_mock_completion(
                tool_calls=[{
                    "id": "call_bad_01",
                    "name": "get_order",
                    "arguments": "{order_id: broken json without quotes",
                }],
                finish_reason="tool_calls",
            )
        )
        provider = OpenAIProvider(api_key="sk-test", client=mock_client)
        result = await provider.chat_step(
            messages=[{"role": "user", "content": "test"}],
            tools=[{"name": "get_order", "description": "lookup", "inputSchema": {}}],
        )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "get_order"
        assert "_malformed_arguments" in result.tool_calls[0].arguments
        assert "_error" in result.tool_calls[0].arguments

    def test_confirm_resolution_excluded_from_openai_tools(self):
        provider = OpenAIProvider(api_key="sk-test", client=MagicMock())
        tools = [
            {"name": "get_order", "description": "Allowed"},
            {"name": "confirm_resolution", "description": "Forbidden state-changing tool"},
            {"name": "check_replacement_options", "description": "Allowed"},
        ]
        formatted = provider._format_tools_for_openai(tools)
        tool_names = [t["function"]["name"] for t in formatted]
        assert "get_order" in tool_names
        assert "check_replacement_options" in tool_names
        assert "confirm_resolution" not in tool_names

    @pytest.mark.anyio
    async def test_exact_request_parameters_audit(self):
        """Audits that chat_step passes the exact documented parameters for gpt-6-luna."""
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_mock_completion(content="Answer", finish_reason="stop")
        )
        provider = OpenAIProvider(api_key="sk-test", model="gpt-6-luna", client=mock_client)
        tools = [{"name": "get_order", "description": "Fetch order", "inputSchema": {"type": "object"}}]

        await provider.chat_step(messages=[{"role": "user", "content": "hello"}], tools=tools)

        assert mock_client.chat.completions.create.called
        kwargs = mock_client.chat.completions.create.call_args[1]

        # Audit documented parameters:
        assert kwargs["model"] == "gpt-6-luna"
        assert kwargs["reasoning_effort"] == "none", "reasoning_effort must be explicitly 'none' for tool calling in Chat Completions"
        assert kwargs["max_completion_tokens"] == 400, "Must use modern documented max_completion_tokens parameter"
        assert "max_tokens" not in kwargs, "Deprecated max_tokens should not be passed when max_completion_tokens is supported"
        assert kwargs["temperature"] == 0.1, "temperature=0.1 must be set and is compatible with reasoning_effort='none'"
        assert kwargs["timeout"] == 15.0
        assert kwargs["tool_choice"] == "auto"
        assert len(kwargs["tools"]) == 1
        assert kwargs["tools"][0]["function"]["name"] == "get_order"


class TestOpenAIErrorHandling:
    """Verifies that API errors are caught, sanitized, and classified correctly."""

    @pytest.mark.anyio
    async def test_authentication_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=AuthenticationError(
                message="Incorrect API key provided: sk-secret-12345",
                response=MagicMock(status_code=401),
                body={"error": {"message": "Invalid API key"}},
            )
        )
        provider = OpenAIProvider(api_key="sk-test", client=mock_client)

        with pytest.raises(OpenAIAuthError) as exc_info:
            await provider.chat_step(messages=[{"role": "user", "content": "hi"}], tools=[])

        err_str = str(exc_info.value)
        assert "OpenAI authentication failed" in err_str
        assert "sk-secret-12345" not in err_str  # Key never leaked

    @pytest.mark.anyio
    async def test_rate_limit_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RateLimitError(
                message="Rate limit reached for requests per minute",
                response=MagicMock(status_code=429),
                body={"error": {"message": "Rate limit reached"}},
            )
        )
        provider = OpenAIProvider(api_key="sk-test", client=mock_client)

        with pytest.raises(OpenAIRateLimitError) as exc_info:
            await provider.chat_step(messages=[{"role": "user", "content": "hi"}], tools=[])

        assert "OpenAI rate limit exceeded" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_insufficient_credit_quota_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RateLimitError(
                message="You exceeded your current quota, please check your plan and billing details.",
                response=MagicMock(status_code=429),
                body={"error": {"message": "insufficient_quota", "code": "insufficient_quota"}},
            )
        )
        provider = OpenAIProvider(api_key="sk-test", client=mock_client)

        with pytest.raises(OpenAIQuotaError) as exc_info:
            await provider.chat_step(messages=[{"role": "user", "content": "hi"}], tools=[])

        err_str = str(exc_info.value)
        assert "credit quota exceeded or insufficient balance" in err_str
        assert "insufficient_quota" in err_str

    @pytest.mark.anyio
    async def test_request_timeout_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=APITimeoutError(request=MagicMock())
        )
        provider = OpenAIProvider(api_key="sk-test", client=mock_client)

        with pytest.raises(OpenAITimeoutError) as exc_info:
            await provider.chat_step(messages=[{"role": "user", "content": "hi"}], tools=[])

        assert "timed out after 15.0 seconds" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_invalid_model_error(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=NotFoundError(
                message="The model 'gpt-nonexistent' does not exist",
                response=MagicMock(status_code=404),
                body={"error": {"message": "Model not found"}},
            )
        )
        provider = OpenAIProvider(api_key="sk-test", model="gpt-nonexistent", client=mock_client)

        with pytest.raises(OpenAIModelError) as exc_info:
            await provider.chat_step(messages=[{"role": "user", "content": "hi"}], tools=[])

        assert "OpenAI model 'gpt-nonexistent' was not found" in str(exc_info.value)


class TestOpenAIOrchestratorIntegration:
    """Verifies end-to-end multi-turn workflows using OpenAIProvider over real MCP."""

    @pytest.fixture
    def test_db(self, tmp_path):
        db_path = str(tmp_path / "test_openai_agent.db")
        return Database(db_path=db_path)

    @pytest.fixture
    def mcp_server_and_transport(self, test_db):
        server = create_mcp_server(db=test_db)
        app = server.streamable_http_app()
        transport = httpx2.ASGITransport(app=app)
        return server, transport

    @pytest.fixture
    def app_client(self, test_db):
        from starlette.testclient import TestClient
        app = create_app(db=test_db)
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client

    @pytest.mark.anyio
    async def test_openai_single_tool_workflow_through_real_mcp(self, mcp_server_and_transport):
        """Simulates OpenAI calling get_order then giving a final answer."""
        server, transport = mcp_server_and_transport
        mock_client = MagicMock()
        turn_1 = make_mock_completion(
            tool_calls=[{"id": "call_1", "name": "get_order", "arguments": {"order_id": "ORD-1001"}}],
            finish_reason="tool_calls",
        )
        turn_2 = make_mock_completion(
            content="Order ORD-1001 retrieved. Item: Ergonomic Wireless Mouse ($49.99).",
            tool_calls=None,
            finish_reason="stop",
        )
        mock_client.chat.completions.create = AsyncMock(side_effect=[turn_1, turn_2])

        openai_provider = OpenAIProvider(api_key="sk-test", client=mock_client)

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    provider=openai_provider,
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run("What is order ORD-1001?")

                assert result.is_success is True
                assert result.is_mock is False
                assert result.provider_name == "openai:gpt-6-luna"
                assert result.iterations == 2
                assert len(result.tool_traces) == 1
                assert result.tool_traces[0].tool == "get_order"
                assert result.tool_traces[0].status == "SUCCESS"
                assert "ORD-1001" in result.assistant_message

    @pytest.mark.anyio
    async def test_openai_multi_tool_workflow_preserves_authoritative_backend_evidence(self, mcp_server_and_transport):
        """Simulates OpenAI calling get_order then check_replacement_options, capturing evidence."""
        server, transport = mcp_server_and_transport
        mock_client = MagicMock()
        turn_1 = make_mock_completion(
            tool_calls=[{"id": "call_1", "name": "get_order", "arguments": {"order_id": "ORD-1001"}}],
            finish_reason="tool_calls",
        )
        turn_2 = make_mock_completion(
            tool_calls=[{
                "id": "call_2",
                "name": "check_replacement_options",
                "arguments": {
                    "order_id": "ORD-1001",
                    "customer_deadline": "2026-10-22T18:00:00",
                    "current_time": "2026-10-20T10:00:00",
                },
            }],
            finish_reason="tool_calls",
        )
        turn_3 = make_mock_completion(
            content="Verified with inventory and logistics: stock is ready and replacement will arrive ahead of deadline.",
            tool_calls=None,
            finish_reason="stop",
        )
        mock_client.chat.completions.create = AsyncMock(side_effect=[turn_1, turn_2, turn_3])

        openai_provider = OpenAIProvider(api_key="sk-test", client=mock_client)

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    provider=openai_provider,
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run(
                    "Check replacement for ORD-1001",
                    context={"order_id": "ORD-1001", "customer_deadline": "2026-10-22T18:00:00"},
                )

                assert result.is_success is True
                assert result.is_mock is False
                assert result.iterations == 3
                assert len(result.tool_traces) == 2
                assert result.tool_traces[0].tool == "get_order"
                assert result.tool_traces[1].tool == "check_replacement_options"
                assert result.tool_traces[1].status == "SUCCESS"
                # Authoritative evidence preserved from deterministic backend
                assert result.resolution_data is not None
                assert len(result.evidence) > 0
                assert any("WH-EAST" in ev for ev in result.evidence)

                # Rigorous Audit: Verify tool-call IDs and tool results preserved across turns
                call_list = mock_client.chat.completions.create.call_args_list
                assert len(call_list) == 3

                # Turn 1: System prompt + User request
                turn1_messages = call_list[0][1]["messages"]
                assert turn1_messages[0]["role"] == "system"
                assert turn1_messages[1]["role"] == "user"
                assert "ORD-1001" in turn1_messages[1]["content"]

                # Turn 2: Preceding assistant call_1 + Tool result call_1
                turn2_messages = call_list[1][1]["messages"]
                assert len(turn2_messages) == 4
                asst_1 = turn2_messages[2]
                assert asst_1["role"] == "assistant"
                assert asst_1["tool_calls"][0]["id"] == "call_1"
                assert asst_1["tool_calls"][0]["function"]["name"] == "get_order"
                tool_1 = turn2_messages[3]
                assert tool_1["role"] == "tool"
                assert tool_1["tool_call_id"] == "call_1"
                assert "ORD-1001" in tool_1["content"]

                # Turn 3: Preceding assistant call_2 + Tool result call_2
                turn3_messages = call_list[2][1]["messages"]
                assert len(turn3_messages) == 6
                asst_2 = turn3_messages[4]
                assert asst_2["role"] == "assistant"
                assert asst_2["tool_calls"][0]["id"] == "call_2"
                assert asst_2["tool_calls"][0]["function"]["name"] == "check_replacement_options"
                tool_2 = turn3_messages[5]
                assert tool_2["role"] == "tool"
                assert tool_2["tool_call_id"] == "call_2"
                assert "meets_any_option" in tool_2["content"]

    @pytest.mark.anyio
    async def test_openai_api_error_returns_clean_error_without_mock_failover(self, mcp_server_and_transport):
        """When OpenAI encounters an error, orchestrator must NOT switch to mock."""
        server, transport = mcp_server_and_transport
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RateLimitError(
                message="Quota exceeded",
                response=MagicMock(status_code=429),
                body={"error": {"code": "insufficient_quota"}},
            )
        )
        openai_provider = OpenAIProvider(api_key="sk-test", client=mock_client)

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    provider=openai_provider,
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run("Check ORD-1001")

                assert result.is_success is False
                # Truthfully attributed to OpenAI provider, NOT mock
                assert result.is_mock is False
                assert result.provider_name == "openai:gpt-6-luna"
                assert "insufficient balance" in result.error
                assert "Agent Error:" in result.assistant_message

    @pytest.mark.anyio
    async def test_openai_confirmation_attempt_strictly_blocked(self, mcp_server_and_transport):
        """If OpenAI attempts to invoke confirm_resolution, it must be intercepted and blocked."""
        server, transport = mcp_server_and_transport
        mock_client = MagicMock()
        turn_malicious = make_mock_completion(
            tool_calls=[{
                "id": "call_hack",
                "name": "confirm_resolution",
                "arguments": {"order_id": "ORD-1001", "customer_agreed": True},
            }],
            finish_reason="tool_calls",
        )
        mock_client.chat.completions.create = AsyncMock(return_value=turn_malicious)

        openai_provider = OpenAIProvider(api_key="sk-test", client=mock_client)

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    provider=openai_provider,
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run("Confirm my replacement automatically")

                assert result.is_success is False
                assert result.is_mock is False
                assert "confirm_resolution" in result.error
                assert "Security Violation" in result.error
                assert result.tool_traces[0].status == "SECURITY_VIOLATION"

    @pytest.mark.anyio
    async def test_openai_iteration_exhaustion_enforced(self, mcp_server_and_transport):
        """Orchestrator stops after max_iterations if model continuously issues tool calls."""
        server, transport = mcp_server_and_transport
        mock_client = MagicMock()
        infinite_call = make_mock_completion(
            tool_calls=[{"id": "call_loop", "name": "get_order", "arguments": {"order_id": "ORD-1001"}}],
            finish_reason="tool_calls",
        )
        mock_client.chat.completions.create = AsyncMock(return_value=infinite_call)

        openai_provider = OpenAIProvider(api_key="sk-test", client=mock_client)

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    provider=openai_provider,
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                    max_iterations=3,
                )

                result = await orchestrator.run("Loop test")

                assert result.is_success is False
                assert result.iterations == 3
                assert "Maximum tool iterations (3) reached" in result.error
                assert result.provider_name == "openai:gpt-6-luna"
                assert result.is_mock is False

    @pytest.mark.anyio
    async def test_openai_provider_scenario_5_context_injected_air_beats_ground(self, mcp_server_and_transport):
        """
        Regression test: When the OpenAI provider model issues check_replacement_options
        without 'current_time', the orchestrator propagates 'current_time' from context.
        Verifies that Expedited Air meets the deadline and is ranked #1 feasible recommendation,
        while Standard Ground misses the deadline.
        """
        server, transport = mcp_server_and_transport
        mock_client = MagicMock()

        # Step 1: Model calls get_order and check_replacement_options WITHOUT current_time
        tc1 = make_mock_completion(
            tool_calls=[
                {
                    "id": "call_ord",
                    "name": "get_order",
                    "arguments": {"order_id": "ORD-1005"},
                },
                {
                    "id": "call_chk",
                    "name": "check_replacement_options",
                    "arguments": {
                        "order_id": "ORD-1005",
                        "customer_deadline": "2026-10-22T12:00:00",
                    },
                },
            ],
            finish_reason="tool_calls",
        )
        # Step 2: Model returns final assistant message
        tc2 = make_mock_completion(
            content="Expedited Air meets your deadline. Standard Ground misses it.",
            finish_reason="stop",
        )
        mock_client.chat.completions.create = AsyncMock(side_effect=[tc1, tc2])

        openai_provider = OpenAIProvider(api_key="sk-test", client=mock_client)

        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
                orchestrator = DoorstepAgentOrchestrator(
                    provider=openai_provider,
                    server_url="http://127.0.0.1:8000/mcp",
                    http_client=http_client,
                )

                result = await orchestrator.run(
                    "Evaluate options for ORD-1005",
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

                # Check trace that current_time was injected from context
                check_trace = next(t for t in result.tool_traces if t.tool == "check_replacement_options")
                assert check_trace.arguments.get("current_time") == "2026-10-20T16:00:00"

                # Check top option is Expedited Air
                top_opt = res_data["top_option"]
                assert top_opt["action_type"] == "REPLACEMENT_EXPEDITED"
                assert top_opt["meets_deadline"] is True
                assert top_opt["cost"] == 14.99
                assert top_opt["estimated_arrival"] == "2026-10-22T03:00:00"

                # Check ground option misses deadline
                ground_opt = [opt for opt in res_data["options"] if "GROUND" in opt["shipping_speed"].upper()][0]
                assert ground_opt["meets_deadline"] is False
                assert ground_opt["estimated_arrival"] == "2026-10-23T15:00:00"

    def test_server_endpoint_with_openai_error_returns_clean_400(self, app_client, monkeypatch):
        """Verifies POST /api/agent/resolve handles missing OpenAI key without crashing."""
        monkeypatch.setenv("DOORSTEP_LLM_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        res = app_client.post(
            "/api/agent/resolve",
            json={"order_id": "ORD-1001", "query": "Check replacement for ORD-1001"},
        )
        assert res.status_code == 400
        data = res.json()
        assert data["status"] == "ERROR"
        assert "OPENAI_API_KEY environment variable is required" in data["error"]
