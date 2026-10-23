# Doorstep Resolve — 3-Minute Hackathon Demo Script

## Video / Presentation Outline

### 1. The Hook (0:00 - 0:35)
- **Problem**: Conversational agents in e-commerce frequently make promises they cannot keep: *"Don't worry, your replacement will arrive tomorrow!"* Customers make travel plans or wait for critical gear, only to find the item was dispatched after carrier cutoffs and arrives late.
- **Solution**: **Doorstep Resolve** — an Alexa+-inspired conversational decision agent and Streamable HTTP Model Context Protocol (MCP) server that **mathematically proves delivery feasibility before promising it**.

---

### 2. Live Feasibility Evaluation (0:35 - 1:35)
- Open `http://127.0.0.1:8000/`.
- **Scenario 1 (Safe Promise)**:
  - Click **Scenario 1 (ORD-1001)**.
  - Show the **Alexa+ Conversational Banner**: *"Good news! I verified stock at WH-EAST-1... arrives comfortably ahead of your deadline."*
  - Expand **Supporting Decision Evidence**: Show the deterministic proof chain (Inventory verification -> Cutoff margin -> Carrier transit -> Deadline margin).
- **Scenario 2 (Missed Deadline Prevention)**:
  - Click **Scenario 2 (ORD-1002)**.
  - Point out the **Amber Warning**: Arrival is 28 hours **past** customer deadline due to missed daily cutoff (16:00) and 48h ground transit.
  - Highlight the agent's voice bubble: *"To prevent broken promises, I will not guarantee this arrival without your explicit consent."*
- **Scenario 5 (Expedited Rescue)**:
  - Click **Scenario 5 (ORD-1005)**.
  - Notice the automatic ranking: **Expedited Air** (Rank 1, meets deadline) vs **Standard Ground** (Rank 2, misses deadline).
- **Interactive Simulation Controls**:
  - Click **"Toggle Cutoff (10:00 ↔ 18:00)"** or use the **"+12h / -12h"** buttons under **Deadline & Simulation Controls** to show how the decision engine dynamically recalculates dispatch dates and arrives at different recommendations in real time.


---

### 3. Guarded Confirmation & Idempotency (1:35 - 2:20)
- Pick the top option in Scenario 1 or Scenario 5.
- Notice the **Explicit Customer Agreement** guardrail:
  - Click **"Test Rejected Flow"** -> Immediately blocked by policy with `CONFIRMATION_REQUIRED`.
  - Check **Explicit Customer Agreement** and click **"Confirm Simulated Resolution"**.
  - Show simulated tracking ID and SQLite audit recording.
- **Test Duplicate Protection**:
  - Re-click **"Confirm Simulated Resolution"** without changing the idempotency token.
  - Show **"Idempotent Replay Verified (Duplicate Prevented)"** banner — safely returned existing receipt without double fulfillment.

---

### 4. MCP Protocol & Audit Transparency (2:20 - 3:00)
- Click **"MCP Activity Trace"** button in top header:
  - Display the real-time Streamable HTTP tool calls: `get_order`, `check_replacement_options`, `confirm_resolution`, `get_case_history`.
  - Expand tool arguments, execution latency (<10ms), and structured JSON responses.
- Point to the **Case Audit Trail**:
  - Show persistent SQLite history timeline tracking all checks, confirmations, and blocked retries.
- **Closing**: *"Doorstep Resolve gives AI shopping assistants the integrity to promise only what logistics can actually deliver."*
