# Doorstep Resolve — Hackathon Submission Checklist

This checklist prepares **Doorstep Resolve** for final submission. All local verification and code preparation are complete. Follow the checklist below to complete external steps (GitHub, deployment, video, and submission portal).

---

## 1. Local Codebase & Hygiene Verification (Completed)
- [x] **No Secrets or Credentials**: Codebase scanned; zero API keys, passwords, or cloud secrets present.
- [x] **No Hardcoded Absolute Paths**: All file paths use relative path references (`Path(__file__).parent`).
- [x] **Git Ignore Rules**: `.gitignore` configured to ignore `*.db`, `node_modules/`, `__pycache__/`, `.pytest_cache/`, and `.env` files.
- [x] **Dependencies Documented**: `requirements.txt` configured with exact minimal backend requirements.
- [x] **Automated Tests**: 109/109 pytest tests passing (`test_agent.py`, `test_doorstep_resolve.py`, `test_integration_api.py`, `test_mcp_client.py`, `test_mcp_server.py`, `test_openai_provider.py`).
- [x] **Standalone Server & Persistence**: Verified via `python verify_standalone_server.py` with process restart and idempotent replay.
- [x] **Frontend Production Build**: Vite production build compiled to `frontend/dist/` and mounted statically at `/`.

---

## 2. GitHub Repository Setup (User Action Required)
> *Note: Antigravity did not push to remote or create repositories per safety instructions.*

To initialize and push this project to GitHub:
```bash
# 1. Navigate to project root
cd "c:\Users\Mr. Daanyal\Desktop\Amazon Hackathon\Doorstep Resolve"

# 2. Initialize a dedicated git repo
git init -b main

# 3. Stage and commit tracked files
git add .
git commit -m "feat: complete Doorstep Resolve decision agent, MCP server, and Alexa+ UI"

# 4. Link to your GitHub repository and push
git remote add origin https://github.com/<your-username>/doorstep-resolve.git
git push -u origin main
```

---

## 3. Deployment Options
The server is completely self-contained. The backend FastAPI/Starlette app automatically serves the compiled React frontend at `http://localhost:8000/` and the Streamable HTTP MCP server at `http://localhost:8000/mcp`.

- **Local Evaluation (Recommended for MCP)**:
  ```bash
  python -m doorstep_resolve.server
  ```
  Evaluators can connect directly using real MCP clients (Claude Desktop, Cursor, or python `mcp` client) to `http://127.0.0.1:8000/mcp`.

- **Cloud Deployment (Optional, e.g. Render / Railway / Fly.io)**:
  - **Build Command**: `pip install -r requirements.txt && cd frontend && npm install && npm run build && cd ..`
  - **Start Command**: `python -m doorstep_resolve.server` (or `uvicorn doorstep_resolve.server:app --host 0.0.0.0 --port $PORT`)
  - **Environment**: Python 3.10+, Node 18+

---

## 4. Demo Video Recording Checklist (2–3 Minutes)
Follow the step-by-step walkthrough in [demo_script.md](file:///c:/Users/Mr.%20Daanyal/Desktop/Amazon%20Hackathon/Doorstep%20Resolve/demo_script.md):
- [ ] **The Hook (0:00–0:35)**: State the problem of conversational e-commerce agents hallucinating promises before verifying cutoffs. Introduce Doorstep Resolve.
- [ ] **Feasibility Walkthrough (0:35–1:35)**:
  - Demonstrate **Scenario 1 (ORD-1001)**: Green badge, on-time delivery, 4-step proof chain.
  - Demonstrate **Scenario 2 (ORD-1002)**: Amber badge, 28-hour lateness warning, agent warns against promising.
  - Demonstrate **Scenario 5 (ORD-1005)**: Expedited Air ranked #1 over Standard Ground.
  - Toggle interactive controls: Click *"Toggle Cutoff (10:00 ↔ 18:00)"* to show real-time re-evaluation.
- [ ] **Guardrails & Idempotency (1:35–2:20)**:
  - Click *"Test Rejected Flow"* to demonstrate policy rejection when agreement is missing.
  - Check *"Explicit Customer Agreement"*, confirm simulated resolution, and show simulated tracking ID.
  - Re-click confirm with the same token to prove duplicate replay prevention (`ALREADY_CONFIRMED`).
- [ ] **MCP Protocol Transparency (2:20–3:00)**:
  - Open *"MCP Activity Trace"* drawer: Show live tool calls, latencies, arguments, and JSON tool returns.
  - Show the SQLite Audit Timeline with full case history.

---

## 5. Submission Form Fields Reference

- **Project Title**: Doorstep Resolve
- **Tagline**: *A pure Python decision agent and Streamable HTTP MCP server that mathematically proves replacement delivery feasibility before promising it to the customer.*
- **Problem Statement**:
  Customer service LLMs and shopping assistants frequently make unfulfillable delivery promises without checking warehouse cutoff times, inventory batches, and carrier schedules, leading to broken deadlines, lost customer trust, and costly manual escalations.
- **Solution & Innovation**:
  Doorstep Resolve evaluates eligibility policies, aggregates warehouse inventory, computes same-day vs. next-day dispatch cutoffs, and deterministically ranks candidate fulfillment options. Every option carries an unforgeable step-by-step proof chain. Action execution is guarded by explicit customer consent and strict idempotency tokens.
- **Model Context Protocol (MCP) Integration**:
  Exposes 4 standardized MCP tools over Streamable HTTP (`/mcp`):
  1. `get_order`: Retrieves order context, policy window, and delivery history.
  2. `check_replacement_options`: Queries inventory and carrier cutoffs, returns ranked feasibility options with audit evidence.
  3. `confirm_resolution`: Idempotently executes resolution with explicit agreement guardrail.
  4. `get_case_history`: Retrieves full persistent audit trail from SQLite.
- **Repository URL**: *(Paste GitHub URL after pushing)*
- **Demo Video URL**: *(Paste YouTube / Loom link after recording)*
