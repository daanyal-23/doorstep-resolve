"""
Doorstep Resolve - Bounded Agent Orchestrator & Provider Interface.

Provides:
- LLMProvider: Abstract provider interface for pluggable model implementations.
- DeterministicMockProvider: Test-only deterministic provider for offline verification.
- DoorstepAgentOrchestrator: Bounded (max 5 iterations) tool-calling execution loop
  invoking genuine MCP tools via DoorstepMCPClient over Streamable HTTP.
- Strict read-only tool gating: confirm_resolution is strictly forbidden and never executed.
"""

import os
import re
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List, Set, FrozenSet

import httpx2
from .config import load_project_env
from .mcp_client import DoorstepMCPClient, MCPToolCallTrace

# Ensure .env configuration is loaded automatically at startup
load_project_env()

try:
    from openai import (
        AsyncOpenAI,
        APIError,
        AuthenticationError,
        RateLimitError,
        APITimeoutError,
        APIConnectionError,
        BadRequestError,
        NotFoundError,
    )
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    AsyncOpenAI = None
    APIError = Exception
    AuthenticationError = Exception
    RateLimitError = Exception
    APITimeoutError = Exception
    APIConnectionError = Exception
    BadRequestError = Exception
    NotFoundError = Exception

logger = logging.getLogger(__name__)

# Constants and security boundaries
ALLOWED_READ_ONLY_TOOLS: FrozenSet[str] = frozenset({
    "get_order",
    "check_replacement_options",
    "get_case_history",
})

DEFAULT_MAX_ITERATIONS: int = 5
DEFAULT_MCP_SERVER_URL: str = os.getenv("DOORSTEP_MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")


# Custom sanitized exceptions for OpenAI Provider
class OpenAIProviderError(Exception):
    """Base exception for OpenAI provider errors."""
    pass


class OpenAIAuthError(OpenAIProviderError):
    """Authentication or invalid API key error."""
    pass


class OpenAIRateLimitError(OpenAIProviderError):
    """Rate limit exceeded."""
    pass


class OpenAIQuotaError(OpenAIProviderError):
    """Account quota or credit limit exhausted ($2.39 credit ceiling protection)."""
    pass


class OpenAIModelError(OpenAIProviderError):
    """Model invalid or not found on account."""
    pass


class OpenAITimeoutError(OpenAIProviderError):
    """Upstream request timeout."""
    pass


class OpenAIConnectionError(OpenAIProviderError):
    """Network connection failure."""
    pass


@dataclass
class ToolCall:
    """Represents a tool call emitted by an LLM provider."""
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    tool_call_id: Optional[str] = None


@dataclass
class LLMStepResult:
    """Represents one step's output from an LLM provider."""
    tool_calls: List[ToolCall] = field(default_factory=list)
    assistant_message: Optional[str] = None
    finish_reason: str = "tool_calls"  # "tool_calls" | "stop"


class LLMProvider(ABC):
    """
    Abstract interface for LLM providers.
    Enables swapping between DeterministicMock, Gemini, Ollama, etc.
    without rewriting the orchestrator loop.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Machine-readable provider name."""
        pass

    @property
    @abstractmethod
    def is_mock(self) -> bool:
        """True if this provider is a mock/test component; False for real LLMs."""
        pass

    @abstractmethod
    async def chat_step(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMStepResult:
        """
        Evaluate conversation history and available tools, returning either
        tool calls to invoke or a final assistant text response.
        """
        pass


class DeterministicMockProvider(LLMProvider):
    """
    Deterministic mock provider for offline testing and development.

    NOT A REAL LLM: This is a rule-based mock component designed strictly for
    testing the orchestrator's multi-turn tool-calling loop, argument serialization,
    and error handling without external API keys or background services.
    """

    @property
    def provider_name(self) -> str:
        return "deterministic-mock-test-provider"

    @property
    def is_mock(self) -> bool:
        return True

    async def chat_step(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMStepResult:
        # 1. Inspect the original user query from the first message
        user_query = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_query = msg.get("content", "")
                break

        # Check for explicit test triggers
        if "TRIGGER_CONFIRMATION_ATTEMPT" in user_query:
            # Malicious/buggy mock attempt to call confirm_resolution
            return LLMStepResult(
                tool_calls=[ToolCall("confirm_resolution", {"order_id": "ORD-1001", "customer_agreed": True})],
                finish_reason="tool_calls",
            )

        if "TRIGGER_UNKNOWN_TOOL" in user_query:
            # Emits a tool call for a tool that doesn't exist
            # If we already have the tool error in messages, return final explanation
            has_tool_res = any(msg.get("role") == "tool" and msg.get("name") == "unknown_mock_tool" for msg in messages)
            if not has_tool_res:
                return LLMStepResult(
                    tool_calls=[ToolCall("unknown_mock_tool", {"arg": "test"})],
                    finish_reason="tool_calls",
                )
            return LLMStepResult(
                assistant_message="[MOCK-TEST-PROVIDER] Handled unknown tool invocation gracefully.",
                finish_reason="stop",
            )

        if "TRIGGER_MALFORMED_ARGS" in user_query:
            # Emits get_order with empty order_id to trigger invalid argument error
            has_tool_res = any(msg.get("role") == "tool" and msg.get("name") == "get_order" for msg in messages)
            if not has_tool_res:
                return LLMStepResult(
                    tool_calls=[ToolCall("get_order", {"order_id": ""})],
                    finish_reason="tool_calls",
                )
            return LLMStepResult(
                assistant_message="[MOCK-TEST-PROVIDER] Detected invalid argument error from get_order.",
                finish_reason="stop",
            )

        if "TRIGGER_INFINITE_LOOP" in user_query:
            # Never stops, continuously requests get_order to test max-iteration bound
            return LLMStepResult(
                tool_calls=[ToolCall("get_order", {"order_id": "ORD-1001"})],
                finish_reason="tool_calls",
            )

        # 2. Extract entities from user query and context
        first_user_msg = next((m for m in messages if m.get("role") == "user"), {})
        msg_context = first_user_msg.get("context") or {}

        order_match = re.search(r"ORD-\d+", user_query)
        if order_match:
            order_id = order_match.group(0)
        else:
            order_id = msg_context.get("order_id") or "ORD-1001"

        deadline_match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?", user_query)
        if deadline_match:
            matched_dl = deadline_match.group(0)
            customer_deadline = matched_dl if len(matched_dl) == 19 else f"{matched_dl}:00"
        elif msg_context.get("customer_deadline"):
            customer_deadline = msg_context.get("customer_deadline")
        else:
            customer_deadline = "2026-10-22T12:00:00" if order_id in ("ORD-1002", "ORD-1005") else ("2026-10-25T18:00:00" if order_id in ("ORD-1003", "ORD-1004") else "2026-10-22T18:00:00")

        if msg_context.get("current_time"):
            current_time_val = msg_context.get("current_time")
        else:
            current_time_val = "2026-10-20T16:00:00" if order_id == "ORD-1005" else ("2026-10-20T15:30:00" if order_id == "ORD-1002" else ("2026-10-20T11:00:00" if order_id in ("ORD-1003", "ORD-1004") else "2026-10-20T10:00:00"))

        # 3. Track which tools have executed so far
        executed_tools: Dict[str, Dict[str, Any]] = {}
        for msg in messages:
            if msg.get("role") == "tool":
                name = msg.get("name", "")
                try:
                    executed_tools[name] = json.loads(msg.get("content", "{}"))
                except Exception:
                    executed_tools[name] = {}

        # 4. Multi-step reasoning state machine
        query_lower = user_query.lower()
        wants_replacement = any(w in query_lower for w in ("replacement", "deadline", "check-options", "arrive", "feasible"))
        wants_history = any(w in query_lower for w in ("history", "timeline", "audit", "events"))
        is_multitool_investigation = "investigate" in query_lower or (wants_replacement and wants_history)

        # Step A: Need order details first
        if "get_order" not in executed_tools:
            return LLMStepResult(
                tool_calls=[ToolCall("get_order", {"order_id": order_id})],
                finish_reason="tool_calls",
            )

        order_res = executed_tools.get("get_order", {})
        if order_res.get("status") != "SUCCESS":
            return LLMStepResult(
                assistant_message=f"[MOCK-TEST-PROVIDER] Order lookup failed: {order_res.get('error', 'Order not found')}",
                finish_reason="stop",
            )

        order_data = order_res.get("order", {})

        # Step B: Need replacement options if requested
        if (wants_replacement or is_multitool_investigation) and "check_replacement_options" not in executed_tools:
            return LLMStepResult(
                tool_calls=[
                    ToolCall(
                        "check_replacement_options",
                        {
                            "order_id": order_id,
                            "customer_deadline": customer_deadline,
                            "current_time": current_time_val,
                        },
                    )
                ],
                finish_reason="tool_calls",
            )

        # Step C: Need case history if requested
        if (wants_history or is_multitool_investigation) and "get_case_history" not in executed_tools:
            return LLMStepResult(
                tool_calls=[ToolCall("get_case_history", {"order_id": order_id})],
                finish_reason="tool_calls",
            )

        # Step D: Synthesis of results
        options_res = executed_tools.get("check_replacement_options")
        history_res = executed_tools.get("get_case_history")

        parts = [
            f"[MOCK-TEST-PROVIDER] Analysis for order {order_id} ({order_data.get('item_name', 'Item')}, ${order_data.get('price', 0.0):.2f}):"
        ]

        if options_res:
            meets_any = options_res.get("meets_any_option", False)
            top_opt = options_res.get("top_option") or {}
            if meets_any:
                parts.append(
                    f"Replacement feasible via {top_opt.get('warehouse_id')} using {top_opt.get('carrier')} "
                    f"({top_opt.get('shipping_speed')}), estimated arrival {top_opt.get('estimated_arrival')}."
                )
            elif not top_opt.get("eligible", True):
                reason = top_opt.get("reason", "Ineligible replacement.")
                parts.append(f"Replacement is blocked/ineligible: {reason}")
            else:
                reason = top_opt.get("reason", "Misses deadline.")
                parts.append(f"No delivery option meets the customer deadline: {reason}")

        if history_res:
            count = history_res.get("event_count", len(history_res.get("events", [])))
            parts.append(f"Persistent audit timeline contains {count} recorded events.")

        if not options_res and not history_res:
            parts.append(f"Delivered on {order_data.get('delivered_at')}. Policy allows replacement: {bool(order_data.get('replacement_allowed', 1))}.")

        return LLMStepResult(
            assistant_message=" ".join(parts),
            finish_reason="stop",
        )


class OpenAIProvider(LLMProvider):
    """
    Genuine OpenAI API Provider for Doorstep Resolve.

    Integrates OpenAI Chat Completions API with native tool/function calling.
    Configured via:
    - DOORSTEP_LLM_PROVIDER=openai
    - OPENAI_API_KEY (required, read strictly from environment)
    - OPENAI_MODEL (defaults to 'gpt-6-luna')
    - OPENAI_BASE_URL (optional custom endpoint)

    Credit protection & safety:
    - Bounded max_tokens (default 400) to protect the account's $2.39 credit balance
    - Strict request timeout of 15 seconds
    - Temperature 0.1 for high determinism and grounded factuality
    - System prompt strictly instructing the model that backend verification is authoritative
      and confirmation is prohibited
    - Sanitizes all errors; never exposes OPENAI_API_KEY to logs, responses, or client
    """

    DEFAULT_MODEL: str = "gpt-6-luna"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        client: Optional[Any] = None,
        max_tokens: int = 400,
        request_timeout: float = 15.0,
        reasoning_effort: Optional[str] = None,
    ):
        if not OPENAI_AVAILABLE and client is None:
            raise ImportError(
                "The 'openai' Python package is required to use OpenAIProvider. "
                "Install it via 'pip install openai>=1.0.0'."
            )

        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        if not resolved_key and client is None:
            raise ValueError(
                "OPENAI_API_KEY environment variable is required when using OpenAIProvider. "
                "Please configure OPENAI_API_KEY in your environment."
            )

        self.model = model or os.getenv("OPENAI_MODEL", self.DEFAULT_MODEL)
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout
        self.reasoning_effort = (
            reasoning_effort
            if reasoning_effort is not None
            else os.getenv("OPENAI_REASONING_EFFORT", "none")
        )

        if client is not None:
            self.client = client
        else:
            self.client = AsyncOpenAI(
                api_key=resolved_key,
                base_url=self.base_url,
                timeout=self.request_timeout,
            )

    @property
    def provider_name(self) -> str:
        return f"openai:{self.model}"

    @property
    def is_mock(self) -> bool:
        return False

    def _format_messages_for_openai(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        system_prompt = (
            "You are the Alexa+ Conversational Assistant for Doorstep Resolve.\n"
            "Your role is to investigate order replacement feasibility and clearly explain delivery options to customers.\n\n"
            "STRICT OPERATIONAL RULES:\n"
            "1. The deterministic backend is authoritative on inventory, eligibility, shipping methods, arrival times, and deadline feasibility. NEVER invent, hallucinate, or contradict tool evidence.\n"
            "2. You only have access to read-only tools: get_order, check_replacement_options, get_case_history.\n"
            "3. NEVER attempt to call 'confirm_resolution' or confirm an order replacement. Replacement confirmation requires explicit separate customer confirmation in the UI.\n"
            "4. Be concise, direct, and factual. Always state clearly whether the replacement can arrive before the customer's deadline.\n"
            "5. If check_replacement_options indicates every option misses the deadline (meets_any_option is false and all options have meets_deadline=false), explicitly state that no delivery option meets the customer's deadline. If an option is blocked due to out-of-stock inventory or expired policy return window, clearly explain that exact reason.\n"
            "6. When calling 'check_replacement_options' or 'get_order', ALWAYS include the 'current_time' parameter if provided in the context or query so warehouse dispatch cutoffs and transit calculations evaluate against the simulated scenario time rather than host clock time."
        )

        formatted: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        for msg in messages:
            role = msg.get("role")
            if role == "user":
                content = msg.get("content", "")
                ctx = msg.get("context")
                if ctx:
                    ctx_str = ", ".join(f"{k}={v}" for k, v in ctx.items() if v)
                    content = f"{content}\n[Context: {ctx_str}]"
                formatted.append({"role": "user", "content": content})
            elif role == "assistant":
                asst_msg: Dict[str, Any] = {"role": "assistant"}
                content_val = msg.get("content")
                # When tool calls are present, empty string is normalized to None per OpenAI spec
                asst_msg["content"] = content_val if content_val else None
                if msg.get("tool_calls"):
                    asst_msg["tool_calls"] = msg["tool_calls"]
                formatted.append(asst_msg)
            elif role == "tool":
                formatted.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", f"call_{msg.get('name', 'tool')}"),
                    "content": msg.get("content", "{}"),
                })

        return formatted

    def _format_tools_for_openai(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        openai_tools: List[Dict[str, Any]] = []
        for tool in tools:
            name = tool.get("name")
            if name not in ALLOWED_READ_ONLY_TOOLS:
                continue
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {
                        "type": "object",
                        "properties": {},
                    }),
                },
            })
        return openai_tools

    async def chat_step(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMStepResult:
        openai_tools = self._format_tools_for_openai(tools)
        formatted_messages = self._format_messages_for_openai(messages)

        create_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": 0.1,
            "max_completion_tokens": self.max_tokens,
            "timeout": self.request_timeout,
        }
        if openai_tools:
            create_kwargs["tools"] = openai_tools
            create_kwargs["tool_choice"] = "auto"

        # Explicitly configure reasoning_effort="none" for GPT-6 Luna function calling in Chat Completions
        if self.reasoning_effort is not None:
            create_kwargs["reasoning_effort"] = self.reasoning_effort

        try:
            try:
                response = await self.client.chat.completions.create(**create_kwargs)
            except BadRequestError as bad_req_err:
                err_str = str(bad_req_err)
                if "reasoning_effort" in err_str:
                    create_kwargs.pop("reasoning_effort", None)
                    response = await self.client.chat.completions.create(**create_kwargs)
                elif "max_completion_tokens" in err_str and "max_tokens" in err_str:
                    create_kwargs.pop("max_completion_tokens", None)
                    create_kwargs["max_tokens"] = self.max_tokens
                    response = await self.client.chat.completions.create(**create_kwargs)
                else:
                    raise
        except AuthenticationError as auth_err:
            sanitized = "OpenAI authentication failed: Invalid or expired API key. Please verify your OPENAI_API_KEY environment variable."
            logger.error(sanitized)
            raise OpenAIAuthError(sanitized) from auth_err
        except RateLimitError as rl_err:
            err_str = str(rl_err).lower()
            code = getattr(rl_err, "code", "") or ""
            if "insufficient_quota" in err_str or "quota" in err_str or "credit" in err_str or code == "insufficient_quota":
                sanitized = "OpenAI credit quota exceeded or insufficient balance (HTTP 429: insufficient_quota). Please check your OpenAI account billing balance or project spend limits."
                logger.error(sanitized)
                raise OpenAIQuotaError(sanitized) from rl_err
            else:
                sanitized = "OpenAI rate limit exceeded (HTTP 429). Please wait before retrying."
                logger.error(sanitized)
                raise OpenAIRateLimitError(sanitized) from rl_err
        except NotFoundError as nf_err:
            sanitized = f"OpenAI model '{self.model}' was not found or is not accessible on this account (HTTP 404). Check OPENAI_MODEL setting."
            logger.error(sanitized)
            raise OpenAIModelError(sanitized) from nf_err
        except APITimeoutError as to_err:
            sanitized = f"OpenAI request timed out after {self.request_timeout} seconds. The upstream API took too long to respond."
            logger.error(sanitized)
            raise OpenAITimeoutError(sanitized) from to_err
        except APIConnectionError as conn_err:
            sanitized = "Failed to establish network connection to OpenAI API endpoint. Please check network connectivity."
            logger.error(sanitized)
            raise OpenAIConnectionError(sanitized) from conn_err
        except APIError as api_err:
            sanitized = f"OpenAI API returned an error ({getattr(api_err, 'status_code', 'unknown')}): {api_err.message if hasattr(api_err, 'message') else str(api_err)}"
            logger.error(sanitized)
            raise OpenAIProviderError(sanitized) from api_err
        except (OpenAIProviderError, ValueError, TypeError):
            raise
        except Exception as generic_err:
            sanitized = f"Unexpected error during OpenAI completion: {str(generic_err)}"
            logger.error(sanitized)
            raise OpenAIProviderError(sanitized) from generic_err

        if not response.choices:
            return LLMStepResult(
                assistant_message="OpenAI returned an empty response with no choices.",
                finish_reason="stop",
            )

        choice = response.choices[0]
        msg = choice.message
        finish_reason = choice.finish_reason

        tool_calls: List[ToolCall] = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                call_id = getattr(tc, "id", None) or f"call_{len(tool_calls)}"
                fn = getattr(tc, "function", None)
                fn_name = getattr(fn, "name", "") if fn else ""
                raw_args = getattr(fn, "arguments", "{}") if fn else "{}"

                try:
                    parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError as decode_err:
                    logger.warning(f"Malformed arguments in OpenAI tool call {fn_name}: {raw_args}")
                    parsed_args = {"_malformed_arguments": raw_args, "_error": str(decode_err)}

                tool_calls.append(ToolCall(tool_name=fn_name, arguments=parsed_args, tool_call_id=call_id))

        if tool_calls:
            return LLMStepResult(
                tool_calls=tool_calls,
                assistant_message=getattr(msg, "content", None),
                finish_reason="tool_calls",
            )

        return LLMStepResult(
            assistant_message=getattr(msg, "content", "") or "",
            finish_reason="stop",
        )


def get_default_provider() -> LLMProvider:
    """
    Factory to instantiate the configured LLMProvider.
    Controlled by DOORSTEP_LLM_PROVIDER:
    - 'mock' (default): DeterministicMockProvider for safe offline testing
    - 'openai': Genuine OpenAIProvider
    Other providers (e.g. gemini, ollama) are strictly unsupported per Milestone D1 specifications.
    """
    provider_type = os.getenv("DOORSTEP_LLM_PROVIDER", "mock").strip().lower()
    if provider_type in ("mock", "deterministic", "test"):
        return DeterministicMockProvider()
    elif provider_type == "openai":
        return OpenAIProvider()
    else:
        raise ValueError(
            f"Unsupported DOORSTEP_LLM_PROVIDER: '{provider_type}'. "
            "Supported providers are 'mock' and 'openai'. Automatic failover is disabled."
        )


@dataclass
class AgentOrchestratorResult:
    """Structured response returned by the DoorstepAgentOrchestrator."""
    assistant_message: str
    tool_traces: List[MCPToolCallTrace] = field(default_factory=list)
    iterations: int = 0
    is_success: bool = True
    evidence: List[str] = field(default_factory=list)
    resolution_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    provider_name: str = "unknown"
    is_mock: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for API response and testing."""
        return {
            "assistant_message": self.assistant_message,
            "tool_traces": [t.to_dict() for t in self.tool_traces],
            "iterations": self.iterations,
            "is_success": self.is_success,
            "evidence": self.evidence,
            "resolution_data": self.resolution_data,
            "error": self.error,
            "provider_name": self.provider_name,
            "is_mock": self.is_mock,
        }


class DoorstepAgentOrchestrator:
    """
    Bounded conversational agent orchestrator for Doorstep Resolve.

    Guarantees:
    1. Maximum 5 tool iterations (preventing runaway cycles).
    2. Read-only tool gating: confirm_resolution is strictly excluded from tools
       exposed to the model, and blocked from execution if attempted.
    3. All tools are invoked through DoorstepMCPClient using real Streamable HTTP.
    4. Gathers genuine MCPToolCallTrace telemetry for frontend inspection.
    5. Clean error handling with provider attribution; no silent fallback to mock.
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        server_url: str = DEFAULT_MCP_SERVER_URL,
        http_client: Optional[httpx2.AsyncClient] = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ):
        self.provider = provider if provider is not None else get_default_provider()
        self.server_url = server_url
        self.http_client = http_client
        self.max_iterations = max_iterations

    async def run(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentOrchestratorResult:
        """
        Executes the bounded tool-calling loop for a user query.
        """
        tool_traces: List[MCPToolCallTrace] = []
        evidence: List[str] = []
        resolution_data: Optional[Dict[str, Any]] = None

        # Build initial message history
        messages: List[Dict[str, Any]] = [{"role": "user", "content": query}]
        if context:
            messages[0]["context"] = context

        client = DoorstepMCPClient(
            server_url=self.server_url,
            http_client=self.http_client,
        )

        try:
            await client.connect()

            # 1. Discover tools and apply strict read-only gating
            all_server_tools = await client.list_tools()
            exposed_tools = [
                tool for tool in all_server_tools
                if tool["name"] in ALLOWED_READ_ONLY_TOOLS
            ]

            # Critical Safeguard: Verify confirm_resolution is never exposed
            assert not any(t["name"] == "confirm_resolution" for t in exposed_tools), (
                "Security Breach: confirm_resolution must never be exposed to the conversational agent."
            )

            # 2. Bounded reasoning loop
            for iteration in range(1, self.max_iterations + 1):
                try:
                    step_result = await self.provider.chat_step(messages, exposed_tools)
                except Exception as exc:
                    logger.error(f"Provider '{self.provider.provider_name}' error at iteration {iteration}: {exc}")
                    return AgentOrchestratorResult(
                        assistant_message=f"Agent Error: {str(exc)}",
                        tool_traces=tool_traces,
                        iterations=iteration,
                        is_success=False,
                        error=str(exc),
                        evidence=evidence,
                        resolution_data=resolution_data,
                        provider_name=self.provider.provider_name,
                        is_mock=self.provider.is_mock,
                    )

                # If provider produced a final message with no tool calls, we are done
                if step_result.finish_reason == "stop" or (step_result.assistant_message and not step_result.tool_calls):
                    return AgentOrchestratorResult(
                        assistant_message=step_result.assistant_message or "",
                        tool_traces=tool_traces,
                        iterations=iteration,
                        is_success=True,
                        evidence=evidence,
                        resolution_data=resolution_data,
                        provider_name=self.provider.provider_name,
                        is_mock=self.provider.is_mock,
                    )

                # Handle tool calls
                if not step_result.tool_calls:
                    # No tool calls and no message
                    break

                # Append assistant message with tool calls to conversation history
                openai_formatted_calls = []
                for i, tc in enumerate(step_result.tool_calls):
                    call_id = tc.tool_call_id or f"call_{iteration}_{i}"
                    tc.tool_call_id = call_id
                    openai_formatted_calls.append({
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else str(tc.arguments),
                        }
                    })

                messages.append({
                    "role": "assistant",
                    "content": step_result.assistant_message or "",
                    "tool_calls": openai_formatted_calls,
                })

                for idx, tool_call in enumerate(step_result.tool_calls):
                    name = tool_call.tool_name
                    args = tool_call.arguments
                    call_id = tool_call.tool_call_id or f"call_{iteration}_{idx}"

                    # Safeguard: Block confirm_resolution or any non-whitelisted tool
                    if name == "confirm_resolution":
                        error_msg = (
                            "Security Violation: 'confirm_resolution' is a restricted state-changing tool "
                            "and cannot be invoked by the conversational agent. Explicit user confirmation is required."
                        )
                        logger.warning(error_msg)
                        violation_trace = MCPToolCallTrace(
                            tool=name,
                            arguments=args,
                            response={"error": error_msg, "status": "SECURITY_VIOLATION"},
                            duration_ms=1,
                            timestamp=datetime.now().strftime("%H:%M:%S"),
                            status="SECURITY_VIOLATION",
                            is_error=True,
                        )
                        tool_traces.append(violation_trace)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": name,
                            "content": json.dumps({"status": "SECURITY_VIOLATION", "error": error_msg}),
                        })
                        return AgentOrchestratorResult(
                            assistant_message=f"Action Blocked: {error_msg}",
                            tool_traces=tool_traces,
                            iterations=iteration,
                            is_success=False,
                            error=error_msg,
                            provider_name=self.provider.provider_name,
                            is_mock=self.provider.is_mock,
                        )

                    if name not in ALLOWED_READ_ONLY_TOOLS:
                        error_msg = f"Unknown or unauthorized tool: '{name}'. Only read-only tools are allowed."
                        logger.warning(error_msg)
                        trace = MCPToolCallTrace(
                            tool=name,
                            arguments=args,
                            response={"error": error_msg, "status": "UNAUTHORIZED_TOOL"},
                            duration_ms=1,
                            timestamp=datetime.now().strftime("%H:%M:%S"),
                            status="ERROR",
                            is_error=True,
                        )
                        tool_traces.append(trace)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "name": name,
                            "content": json.dumps({"status": "ERROR", "error": error_msg}),
                        })
                        continue

                    # Ensure simulation context is propagated to read-only tool calls if omitted
                    if context and isinstance(args, dict):
                        is_same_order = not args.get("order_id") or args.get("order_id") == context.get("order_id")
                        if name in ("check_replacement_options", "get_order"):
                            if "current_time" in context and not args.get("current_time") and is_same_order:
                                args["current_time"] = context["current_time"]
                        if name == "check_replacement_options":
                            if "customer_deadline" in context and not args.get("customer_deadline") and is_same_order:
                                args["customer_deadline"] = context["customer_deadline"]
                            if "order_id" in context and not args.get("order_id"):
                                args["order_id"] = context["order_id"]

                    # Execute valid read-only tool via genuine MCP protocol
                    trace = await client.call_tool(name, args)
                    tool_traces.append(trace)

                    # Extract resolution evidence if available
                    if name == "check_replacement_options" and trace.status == "SUCCESS":
                        resolution_data = trace.response
                        top = trace.response.get("top_option") or {}
                        if top.get("evidence"):
                            evidence.extend(top["evidence"])

                    # Append tool result to conversation history for next reasoning step
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": json.dumps(trace.response),
                    })

            # If loop completed without a stop signal, iteration limit was reached
            exhaustion_msg = f"Maximum tool iterations ({self.max_iterations}) reached without completing resolution."
            return AgentOrchestratorResult(
                assistant_message="I reached the maximum reasoning iterations while evaluating your delivery options. Please verify your order ID or deadline.",
                tool_traces=tool_traces,
                iterations=self.max_iterations,
                is_success=False,
                error=exhaustion_msg,
                evidence=evidence,
                resolution_data=resolution_data,
                provider_name=self.provider.provider_name,
                is_mock=self.provider.is_mock,
            )

        finally:
            await client.close()
