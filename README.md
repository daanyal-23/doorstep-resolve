# Doorstep Resolve

A pure Python decision agent and Model Context Protocol (MCP) server that determines whether an e-commerce shopping replacement can meet a customer's deadline before promising it to the customer.

## Key Capabilities

1. **Eligibility & Policy Verification**: Validates whether the order is within the return/replacement policy window, ensures `current_time` does not precede `order.delivered_at`, and checks if replacements are permitted.
2. **Strict Timezone Validation**: Enforces consistent timezone awareness across all inputs (`delivered_at`, `customer_deadline`, `current_time`) preventing unhandled runtime `TypeError` exceptions.
3. **Multi-Lot Inventory Aggregation**: Aggregates multiple inventory lots/batches per warehouse into unique fulfillment options, preventing duplicate recommendations.
4. **Dispatch Cutoff & Transit Estimation**: Determines same-day vs. next-day dispatch based on carrier cutoffs, calculating precise arrival times and deadline margins.
5. **Deterministic Ranking (No Host-OS Dependency)**: Ranks candidate fulfillment routes without operating-system-dependent `timestamp()` calls:
   - **Tier 1**: Eligible and meets the deadline (ranked by earliest arrival, then lowest cost).
   - **Tier 2**: Eligible but misses the deadline (ranked by earliest arrival).
   - **Tier 3**: Ineligible (e.g. out of stock, policy expired, or unroutable).
6. **Streamable HTTP MCP Server**: Exposes an MCP endpoint (`/mcp`) supporting standard Streamable HTTP transports with SQLite persistence.
7. **Idempotent Confirmation Guard**: Requires explicit customer agreement before recording a resolution and guarantees idempotent replays with duplicate prevention.

---

## Architecture & Code Structure

```
Doorstep Resolve/
├── doorstep_resolve/
│   ├── __init__.py               # Package exports (models, resolver, db, server, agent)
│   ├── agent.py                  # Bounded Agent Orchestrator & LLM Providers (Mock, OpenAI)
│   ├── config.py                 # Environment loader (.env auto-discovery)
│   ├── db.py                     # SQLite persistence layer (orders, inventory, resolutions, case_history)
│   ├── mcp_client.py             # Streamable HTTP MCP Client with pooling & latency tracing
│   ├── models.py                 # Dataclasses (Order, Policy, InventoryItem, ShippingEstimate, ResolutionOption)
│   ├── resolver.py               # Core pure Python decision engine (`resolve_replacement`)
│   ├── scenarios.py              # 5 synthetic realistic test scenarios
│   └── server.py                 # Streamable HTTP MCP Server & FastAPI web endpoint on port 8000
├── frontend/                     # Alexa+-inspired conversational React + Tailwind interface
│   ├── src/
│   │   ├── components/           # Header, AlexaAssistantCard, ResolutionCards, ConfirmationPanel, etc.
│   │   ├── App.jsx               # Conversational application state & MCP tool call orchestration
│   │   └── main.jsx
│   ├── dist/                     # Production compiled static build mounted by server
│   └── package.json
├── tests/
│   ├── test_agent.py             # Orchestrator loop & safety boundaries (12 tests)
│   ├── test_doorstep_resolve.py  # Unit & regression tests for resolver edge cases (20 tests)
│   ├── test_integration_api.py   # End-to-end integration API & workflow tests (27 tests)
│   ├── test_mcp_client.py        # Streamable HTTP MCP Client & connection tests (11 tests)
│   ├── test_mcp_server.py        # Tests for MCP tools, persistence, idempotency (13 tests)
│   └── test_openai_provider.py   # OpenAI tool-calling, mock errors & credential handling (26 tests)
├── demo.py                       # Formatted scenario demonstration runner
├── verify_standalone_server.py   # Standalone process, persistence across restart & MCP tool verification
├── doorstep_resolve.db           # SQLite database (auto-seeded with synthetic scenarios)
├── LICENSE                       # Open-source MIT License
├── requirements.txt              # Minimal Python dependencies
└── README.md                     # Project documentation
```

---

## MCP Tools Specification

The MCP server exposes four tools over Streamable HTTP (`/mcp`):

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `get_order` | `order_id: str` | Retrieves order, delivery timestamp, item metadata, and return window from SQLite. |
| `check_replacement_options` | `order_id: str`, `customer_deadline: str`, `current_time: Optional[str]` | Queries persistent inventory and carrier cutoffs, executes deterministic resolution logic, logs event to case history, and returns ranked fulfillment options with step-by-step evidence. |
| `confirm_resolution` | `order_id: str`, `option_id: str`, `customer_agreed: bool`, `idempotency_key: str`, `case_id: Optional[str]`, `customer_notes: Optional[str]` | Requires `customer_agreed=True` and records the resolution in SQLite. Idempotent: retries with the same `idempotency_key` safely return the existing record without duplicate actions. |
| `get_case_history` | `order_id: Optional[str]`, `case_id: Optional[str]` | Retrieves persistent audit trail logs for all checks, confirmations, and retries. |

---

## Execution Modes & Data Realism

Doorstep Resolve provides a clean separation between LLM execution modes, MCP tool transport, and fulfillment data:

| Dimension | Mock Mode (Default) | Live API Mode |
| :--- | :--- | :--- |
| **Provider** | `DeterministicMockProvider` | `OpenAIProvider` |
| **Model** | Built-in test provider | `gpt-6-luna` (configurable via `OPENAI_MODEL`) |
| **Network Calls** | **Zero external calls** (100% offline) | Upstream HTTPS calls to `api.openai.com` |
| **Credentials Required** | **None** | `OPENAI_API_KEY` (project-scoped `sk-proj-...`) |
| **Test Suite Coverage** | All 109 automated tests execute offline | Verified via mocked API responses & rate-limit error simulators |
| **Activation** | `DOORSTEP_LLM_PROVIDER=mock` (or unset) | `DOORSTEP_LLM_PROVIDER=openai` |

### Simulated Fulfillment Data
All warehouse inventories, carrier cutoff schedules, order timestamps, and confirmation receipts are **realistic synthetic data**:
- **Pure Mathematical Feasibility**: Transit times and cutoff limits are derived deterministically using temporal arithmetic and carrier schedules.
- **Zero Financial/Carrier Side Effects**: Confirmations create local audit records and simulated tracking identifiers without charging actual credit cards or dispatching physical vehicles.
- **Safe Evaluation**: Evaluators and hackathon judges can safely run end-to-end scenarios, restart the server, and verify idempotent replays without incurring external carrier or logistics charges.

---

## Environment Variables

Copy `.env.example` to `.env` to configure local settings:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `DOORSTEP_LLM_PROVIDER` | `mock` | LLM provider selection: `mock` (offline testing) or `openai` (live OpenAI API). |
| `OPENAI_API_KEY` | *(None)* | Secret OpenAI API key (`sk-proj-...`). Required only when `DOORSTEP_LLM_PROVIDER=openai`. |
| `OPENAI_MODEL` | `gpt-6-luna` | OpenAI model identifier (e.g. `gpt-6-luna`, `gpt-4o-mini`). |
| `OPENAI_REASONING_EFFORT` | `none` | Explicitly `none` to enable function/tool calling in Chat Completions. |
| `DOORSTEP_MCP_SERVER_URL` | `http://127.0.0.1:8000/mcp` | Streamable HTTP MCP server URL. |

---

## Synthetic Scenarios

| Scenario | Situation | Expected Outcome |
| :--- | :--- | :--- |
| **1. Replacement Meets Deadline** | Stock available, transit 24h before cutoff, deadline in 56h. | **Rank 1**: Eligible & Meets Deadline (Safe promise). |
| **2. Replacement Arrives Too Late** | Stock available, but request is past 16:00 cutoff and transit is 48h, missing a tight deadline. | **Rank 1**: Eligible, but Misses Deadline by 28h (Fails constraint). |
| **3. Stock Unavailable** | Within policy window, but 0 inventory across all warehouses. | **Rank 1**: Ineligible (Out of stock explanation). |
| **4. Return Window Expired** | Item delivered 40 days ago under a 30-day policy window. | **Rank 1**: Ineligible (Policy expired by 10 days). |
| **5. Expedited Meets Deadline** | Standard ground transit takes 48h (misses deadline), but Expedited Air arrives in 12h. | **Rank 1**: Expedited (Eligible, meets deadline), **Rank 2**: Standard (Eligible, misses deadline). |

---

## Installation & Setup

### Prerequisites
- Python 3.10+
- Node.js 18+ (for frontend modifications/builds)

### 1. Install Backend Dependencies:
```bash
pip install -r requirements.txt
```

### 2. Frontend Build (Optional, pre-built in `frontend/dist`):
```bash
cd frontend
npm install
npm run build
cd ..
```

---

## Running the Application and Tests

### 1. Run Complete Pytest Suite (109 Tests):
```bash
python -m pytest -v
```


### 2. Run Standalone MCP Server & Persistence Verification:
```bash
python verify_standalone_server.py
```
This launches the server as an independent child process, establishes a genuine Streamable HTTP MCP Client session, queries tools, confirms a resolution, kills the process, relaunches a new process, and verifies that SQLite persists the state and prevents duplicate idempotent retries across server restarts.

### 3. Start the Unified Server (Backend + MCP + Frontend):
```bash
python -m doorstep_resolve.server
```
- **Web UI**: Open `http://127.0.0.1:8000/` in your browser.
- **MCP Endpoint**: `http://127.0.0.1:8000/mcp` (Streamable HTTP for MCP clients).
- **REST Endpoints**: `/api/scenarios`, `/api/orders/{id}`, `/api/check-options`, `/api/confirm`, `/api/history/{id}`.

### 4. Optional: Run Frontend in Hot-Reload Dev Mode:
```bash
cd frontend
npm run dev
```

### 5. Run Demonstration CLI:
```bash
python demo.py
```

---

## Distinctive Demo Story: "Prove Feasibility Before Promising"

In customer support and e-commerce logistics, generative AI agents frequently hallucinate promises ("Don't worry, your replacement will be there tomorrow!") before checking warehouse stock, daily cutoff times, and transit schedules.

**Doorstep Resolve** inverts this pattern:
1. **Never Make An Empty Promise**: The agent mathematically derives transit schedules against daily warehouse cutoffs and carrier transit matrices before presenting any solution to the customer.
2. **Transparent Mathematical Proof**: Every candidate option displays its exact proof chain (inventory lot verification, cutoff margin, transit duration, deadline margin).
3. **Risk Highlighting**: Options that miss the customer's deadline are colored amber/red and explicitly flagged with the exact hours of lateness.
4. **Guarded Idempotency**: No dispatch action is finalized without explicit customer consent and an idempotency token ensuring duplicate requests never generate duplicate orders.
5. **Real-time MCP Activity Trace**: A drawer in the UI displays the exact MCP tool invocations, inputs, responses, and latencies in real time.

---

## Assumptions & Limitations

### Assumptions:
1. **Timezones**: Datetime inputs (`current_time`, `customer_deadline`, `delivered_at`) share a consistent timezone reference (all aware or all naive).
2. **Simulated Fulfillment**: All confirmation actions record simulated tracking identifiers and database receipts without executing external financial charges or carrier API calls.
3. **Dispatch Operations**: Daily dispatch cutoffs are modeled once per carrier/warehouse schedule per day.

### Current Limitations:
1. **Warehouse Geographic Timezones**: `ShippingEstimate` specifies `cutoff_time: time` without a location-specific timezone; cutoffs are evaluated relative to `current_time`'s coordinate space.
2. **Carrier Calendars**: Weekend carrier blackouts (e.g. no Sunday linehaul) and holiday operating schedules are not yet factored in.
3. **Multi-Item Order Split**: Resolves single-item replacement requests; does not split fulfillments across multiple warehouses for multi-quantity orders.

---

## License

This project is licensed under the [MIT License](LICENSE).

