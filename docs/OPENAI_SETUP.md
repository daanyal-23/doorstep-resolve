# Doorstep Resolve — OpenAI API Integration Guide (Milestone D1)

## Overview
Milestone D1 integrates genuine OpenAI tool calling into the Doorstep Resolve conversational orchestrator while strictly preserving deterministic backend authority and credit safety for an account with **$2.39 in API credit**.

---

## 1. Selected Model & Pricing

| Attribute | Specification |
|---|---|
| **Selected Model** | `gpt-6-luna` (configurable via `OPENAI_MODEL`) |
| **Input Pricing** | **$0.10** per 1,000,000 tokens ($0.0001 / 1K tokens) |
| **Output Pricing** | **$0.50** per 1,000,000 tokens ($0.0005 / 1K tokens) |
| **Context Window** | Up to 1,050,000 tokens |
| **Native Capabilities** | Native tool/function calling, strict JSON output schemas, adjustable reasoning controls |
| **Alternative Fallback** | `gpt-4o-mini` ($0.15 / 1M input, $0.60 / 1M output) |

At $0.10 / 1M input tokens and $0.50 / 1M output tokens, a typical Doorstep Resolve resolution query (~350 input tokens, ~100 output tokens across 2 turns) costs approximately **$0.000085** (~0.0085 cents). The existing **$2.39** credit balance is sufficient for more than **28,000 agent resolution queries**.

---

## 2. Dedicated Project & Key Setup (Isolating from ParcelPilot)

To protect existing deployments (such as ParcelPilot) and prevent cross-app credit consumption:

1. Log in to the [OpenAI Platform](https://platform.openai.com/).
2. Navigate to **Organization Settings** > **Projects** and click **Create Project**.
3. Name the project `Doorstep-Resolve`.
4. Inside the `Doorstep-Resolve` project:
   - Navigate to **Project API Keys**.
   - Click **Create new secret key**.
   - Note the project-scoped key prefix: `sk-proj-...`.
   - **Never commit this key or paste it into shared chats or documents.**
5. In **Usage limits** (or Organization Billing):
   - Set a project monthly spend limit (e.g., $1.00 - $2.00).
   - *Note on spend controls:* OpenAI usage limits provide soft alerts and hard request-blocking thresholds, but do not provide an exact zero-latency micro-cap to the single millicent due to upstream reporting batch intervals.

---

## 3. Configuration & Environment Variables

Doorstep Resolve is configured using environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `DOORSTEP_LLM_PROVIDER` | `mock` | `mock` (deterministic test provider) or `openai` (genuine OpenAI API) |
| `OPENAI_API_KEY` | *(None)* | Secret API key (`sk-proj-...`). Required when provider is `openai`. |
| `OPENAI_MODEL` | `gpt-6-luna` | Configurable OpenAI model identifier. |
| `OPENAI_REASONING_EFFORT` | `none` | Explicitly configured to `none` to enable function/tool calling in Chat Completions. |
| `DOORSTEP_MCP_SERVER_URL` | `http://127.0.0.1:8000/mcp` | Streamable HTTP MCP server URL. |

### Documented Request Parameters:
- **`reasoning_effort="none"`**: For GPT-6 Luna in the Chat Completions endpoint (`client.chat.completions.create`), tool/function calling is only permitted when reasoning effort is explicitly set to `"none"`.
- **`max_completion_tokens=400`**: Uses the official output-token ceiling parameter for GPT-6/reasoning models.
- **`temperature=0.1`**: Fully supported and active when `reasoning_effort="none"`.

---

## 4. Built-in Safety & Credit Safeguards

1. **Deterministic Default:**
   Defaults to `DOORSTEP_LLM_PROVIDER=mock`. Automated unit, integration, and CI tests run 100% offline without consuming API credits or requiring credentials.
2. **Conservative Generation Ceiling:**
   `max_tokens=400` and `temperature=0.1` prevent runaway output token generation.
3. **Bounded Reasoning:**
   Maximum of **5 tool iterations**.
4. **Read-Only Tool Boundary:**
   Only `get_order`, `check_replacement_options`, and `get_case_history` are exposed.
   `confirm_resolution` is strictly excluded from the schema and blocked with `SECURITY_VIOLATION` if ever attempted.
5. **Authoritative Evidence:**
   The deterministic backend resolver is authoritative for warehouse stock, transit routes, cutoffs, and policy deadlines. The LLM explains and summarizes backend evidence without inventing alternative facts.
6. **No Silent Mock Fallback:**
   When OpenAI errors occur (e.g. rate limit, credit exhaustion, invalid key), Doorstep Resolve reports a clean, sanitized error and truthfully identifies the provider as OpenAI.

---

## 5. Local Setup & Testing Workflow (Zero Key Pasting in Terminal)

Doorstep Resolve automatically loads configuration from `.env` in the project root on startup. You do not need to paste your secret API key into your terminal.

### Step 1: Create your local `.env` file
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
*(On Linux/macOS: `cp .env.example .env`)*

### Step 2: Add your credentials to `.env`
Open `.env` in your editor and configure:
```ini
DOORSTEP_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-YOUR_ACTUAL_SECRET_KEY
OPENAI_MODEL=gpt-6-luna
```
*(The `.env` file is git-ignored and will never be committed, pushed, or logged.)*

### Step 3: Start the Doorstep Resolve unified server
Simply launch uvicorn without any manual environment-variable assignments:
```powershell
python -m uvicorn doorstep_resolve.server:app --port 8000
```
The server will automatically load `.env` on startup. If an explicit environment variable is set in the shell (e.g. `DOORSTEP_LLM_PROVIDER=mock`), it will take precedence over `.env`.

### Step 4: Run a resolution test
In a separate terminal or web browser:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/agent/resolve" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"order_id": "ORD-1001", "customer_deadline": "2026-10-22T18:00:00"}'
```
Or open `http://127.0.0.1:8000` to test through the Alexa+ UI.

### Expected Output:
- HTTP 200 OK.
- `is_mock`: `false`.
- `provider_name`: `"openai:gpt-6-luna"`.
- `status`: `"SUCCESS"`.
- `tool_traces`: Contains real MCP traces for `get_order` and `check_replacement_options`.
- `assistant_message`: Factual narrative explaining delivery feasibility by the deadline.
