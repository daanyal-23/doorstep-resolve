import React, { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import ScenarioPicker from './components/ScenarioPicker';
import AlexaAssistantCard from './components/AlexaAssistantCard';
import OrderCard from './components/OrderCard';
import DeadlineControl from './components/DeadlineControl';
import ResolutionCards from './components/ResolutionCards';
import ConfirmationPanel from './components/ConfirmationPanel';
import CaseHistoryTimeline from './components/CaseHistoryTimeline';
import ActivityTraceDrawer from './components/ActivityTraceDrawer';

const API_BASE = '/api';

export default function App() {
  const [scenarios, setScenarios] = useState([]);
  const [activeScenarioId, setActiveScenarioId] = useState('scenario_1');
  const [orderId, setOrderId] = useState('ORD-1001');
  const [order, setOrder] = useState(null);

  const [customerDeadline, setCustomerDeadline] = useState('2026-10-22T18:00:00');
  const [currentTime, setCurrentTime] = useState('2026-10-20T10:00:00');

  const [resolutionResult, setResolutionResult] = useState(null);
  const [selectedOption, setSelectedOption] = useState(null);

  const [idempotencyKey, setIdempotencyKey] = useState(`IDEM-ORD-1001-${Math.random().toString(36).substring(2, 6).toUpperCase()}`);
  const [confirmationResult, setConfirmationResult] = useState(null);
  const [caseHistory, setCaseHistory] = useState([]);

  // Authentic MCP Protocol Tool Traces from backend
  const [traceLogs, setTraceLogs] = useState([]);
  const [isTraceOpen, setIsTraceOpen] = useState(false);

  // Agent response state (Clearly identified mock provider output)
  const [assistantMessage, setAssistantMessage] = useState(null);
  const [providerName, setProviderName] = useState('deterministic-mock-test-provider');
  const [isMockProvider, setIsMockProvider] = useState(true);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [backendConnected, setBackendConnected] = useState(true);

  // Active request counter ref to prevent race conditions and stale overwrites
  const activeRequestIdRef = useRef(0);

  // Fetch initial scenario list
  useEffect(() => {
    fetchScenarios();
  }, []);

  const fetchScenarios = async () => {
    try {
      const res = await fetch(`${API_BASE}/scenarios`);
      if (!res.ok) throw new Error("Failed to load scenarios");
      const data = await res.json();
      setScenarios(data.scenarios);
      if (data.provider_name) {
        setProviderName(data.provider_name);
        setIsMockProvider(data.is_mock ?? true);
      }
      setBackendConnected(true);

      // Initialize with first scenario
      if (data.scenarios && data.scenarios.length > 0) {
        selectScenario(data.scenarios[0]);
      }
    } catch (err) {
      console.error(err);
      setBackendConnected(false);
      setError("Cannot connect to Doorstep Resolve backend. Ensure server is running on port 8000.");
    }
  };

  // Switch scenario and trigger agent resolution
  const selectScenario = async (sc) => {
    setActiveScenarioId(sc.id);
    setOrderId(sc.order_id);
    setCustomerDeadline(sc.default_deadline);
    setCurrentTime(sc.default_current_time);
    setSelectedOption(null);
    setConfirmationResult(null);
    setResolutionResult(null);
    setOrder(null);
    setCaseHistory([]);
    setError(null);
    setAssistantMessage(null);

    // Generate fresh idempotency key for this scenario run strictly bound to sc.order_id
    setIdempotencyKey(`IDEM-${sc.order_id}-${Math.random().toString(36).substring(2, 6).toUpperCase()}`);

    // Run backend agent orchestrator for this scenario
    await executeAgentResolve(sc.order_id, sc.default_deadline, sc.default_current_time);
  };

  // Central Agent Orchestrator invocation over POST /api/agent/resolve
  const executeAgentResolve = async (targetOrderId, deadline, simTime, customQuery = null) => {
    const reqId = ++activeRequestIdRef.current;
    setLoading(true);
    setError(null);

    const queryToUse = customQuery || `Evaluate replacement options for order ${targetOrderId} with deadline ${deadline}`;

    try {
      // 1. Invoke Real Backend Agent Orchestrator over Streamable HTTP MCP
      const res = await fetch(`${API_BASE}/agent/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: queryToUse,
          order_id: targetOrderId,
          customer_deadline: deadline,
          current_time: simTime,
        })
      });

      const data = await res.json();

      // Discard stale in-flight response if another scenario or query was triggered
      if (reqId !== activeRequestIdRef.current) return;

      // Update provider attribution whenever returned by backend (even on error responses)
      if (data.provider_name) {
        setProviderName(data.provider_name);
        setIsMockProvider(data.is_mock ?? true);
      }

      if (!res.ok || data.status === 'ERROR') {
        throw new Error(data.error || "Agent resolution failed");
      }

      // Update state with authentic agent response
      setAssistantMessage(data.assistant_message);

      // Populate Activity Trace Drawer strictly with ACTUAL MCP protocol traces from backend
      if (data.tool_traces && data.tool_traces.length > 0) {
        setTraceLogs(data.tool_traces);
      }

      let resolvedOrderId = targetOrderId;

      // If resolution options were evaluated, update cards
      if (data.resolution_data) {
        if (data.resolution_data.order_id) {
          resolvedOrderId = data.resolution_data.order_id;
          setOrderId(resolvedOrderId);
          setIdempotencyKey(prev => (prev && prev.includes(resolvedOrderId)) ? prev : `IDEM-${resolvedOrderId}-${Math.random().toString(36).substring(2, 6).toUpperCase()}`);
        }
        if (data.resolution_data.customer_deadline) {
          setCustomerDeadline(data.resolution_data.customer_deadline);
        }
        if (data.resolution_data.options) {
          setResolutionResult(data.resolution_data);
          const topOpt = data.resolution_data.options[0];
          // Do not mark an infeasible or deadline-missing option as Selected by default
          if (topOpt && topOpt.is_eligible && topOpt.meets_deadline) {
            setSelectedOption({ ...topOpt, order_id: resolvedOrderId });
          } else {
            setSelectedOption(null);
          }
        }
      }

      // Ensure order details are populated in OrderCard
      const getOrderTrace = data.tool_traces?.find(t => t.tool === 'get_order');
      if (getOrderTrace?.response?.order) {
        setOrder(getOrderTrace.response.order);
      } else {
        const ordRes = await fetch(`${API_BASE}/orders/${resolvedOrderId}?current_time=${encodeURIComponent(simTime)}`);
        if (ordRes.ok) {
          const ordData = await ordRes.json();
          if (ordData.order) setOrder(ordData.order);
        }
      }

      // Refresh case history timeline strictly for the resolved order
      await fetchCaseHistory(resolvedOrderId);

    } catch (err) {
      if (reqId === activeRequestIdRef.current) {
        console.error(err);
        setError(err.message);
      }
    } finally {
      if (reqId === activeRequestIdRef.current) {
        setLoading(false);
      }
    }
  };

  // Fetch Case History Timeline (separate audit query without fake MCP traces)
  const fetchCaseHistory = async (targetOrderId) => {
    try {
      const res = await fetch(`${API_BASE}/history/${targetOrderId}`);
      const data = await res.json();
      if (data.status === 'SUCCESS') {
        setCaseHistory(data.events || []);
      }
    } catch (err) {
      console.error("Failed to load history:", err);
    }
  };

  // Re-evaluate on manual deadline/time change
  const handleReevaluate = () => {
    executeAgentResolve(orderId, customerDeadline, currentTime);
  };

  // Handle Conversational User Query
  const handleUserQuery = async (queryText) => {
    const match = queryText.match(/ORD-\d+/);
    let targetOrderId = orderId;
    let targetDeadline = customerDeadline;
    let targetTime = currentTime;

    if (match && match[0] !== orderId) {
      targetOrderId = match[0];
      const sc = scenarios.find(s => s.order_id === targetOrderId);
      if (sc) {
        setActiveScenarioId(sc.id);
        targetDeadline = sc.default_deadline;
        targetTime = sc.default_current_time;
      }
      setOrderId(targetOrderId);
      setCustomerDeadline(targetDeadline);
      setCurrentTime(targetTime);
      setSelectedOption(null);
      setConfirmationResult(null);
      setResolutionResult(null);
      setOrder(null);
      setCaseHistory([]);
      setIdempotencyKey(`IDEM-${targetOrderId}-${Math.random().toString(36).substring(2, 6).toUpperCase()}`);
    }

    await executeAgentResolve(targetOrderId, targetDeadline, targetTime, queryText);
  };

  // Handle Resolution Confirmation (Strictly separate user confirmation flow)
  const handleConfirm = async ({ customerAgreed, customerNotes, overrideKey }) => {
    if (!selectedOption) return;

    const keyToUse = overrideKey || idempotencyKey;
    if (overrideKey) {
      setIdempotencyKey(overrideKey);
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          order_id: orderId,
          option_id: selectedOption.option_id,
          customer_agreed: customerAgreed,
          idempotency_key: keyToUse,
          customer_notes: customerNotes,
        })
      });
      const data = await res.json();

      setConfirmationResult(data);

      // Refresh case history to show recorded event
      await fetchCaseHistory(orderId);

    } catch (err) {
      console.error(err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0b0f19] text-slate-100 flex flex-col font-['Inter',sans-serif]">
      {/* Top Header with Alexa+ branding & MCP Status */}
      <Header 
        toolCallsCount={traceLogs.length}
        onOpenTrace={() => setIsTraceOpen(true)}
        backendConnected={backendConnected}
      />

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Scenario Quick Selector (Scenarios 1 through 5) */}
        <ScenarioPicker 
          scenarios={scenarios}
          activeScenarioId={activeScenarioId}
          onSelectScenario={selectScenario}
          loading={loading}
        />

        {/* Alexa+ Conversational Assistant Card with Real Agent Message & Mock Indicator */}
        <AlexaAssistantCard 
          order={order}
          resolutionResult={resolutionResult}
          customerDeadline={customerDeadline}
          loading={loading}
          error={error}
          agentMessage={assistantMessage}
          providerName={providerName}
          isMock={isMockProvider}
          onSendQuery={handleUserQuery}
        />

        {/* Global Error Banner */}
        {error && (
          <div className="bg-rose-950/60 border border-rose-500/50 rounded-2xl p-4 mb-6 text-rose-300 text-xs flex items-center justify-between">
            <span>{error}</span>
            <button
              onClick={() => handleReevaluate()}
              className="bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 px-3 py-1 rounded-lg text-xs font-semibold"
            >
              Retry
            </button>
          </div>
        )}

        {/* Two-Column Responsive Workspace Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column (5 cols): Order Details + Deadline Controls + SQLite Case History */}
          <div className="lg:col-span-5 space-y-6">
            <OrderCard 
              order={order} 
              loading={loading} 
              currentTime={currentTime}
              resolutionResult={resolutionResult}
            />

            <DeadlineControl 
              customerDeadline={customerDeadline}
              setCustomerDeadline={setCustomerDeadline}
              currentTime={currentTime}
              setCurrentTime={setCurrentTime}
              onEvaluate={handleReevaluate}
              loading={loading}
            />

            <CaseHistoryTimeline 
              events={caseHistory}
              onRefresh={() => fetchCaseHistory(orderId)}
              loading={loading}
            />
          </div>

          {/* Right Column (7 cols): Ranked Resolution Options & Explicit Confirmation */}
          <div className="lg:col-span-7 space-y-6">
            <ResolutionCards 
              options={resolutionResult?.options || []}
              selectedOptionId={selectedOption?.option_id}
              onSelectOption={(opt) => setSelectedOption(opt ? { ...opt, order_id: orderId } : null)}
              customerDeadline={customerDeadline}
              loading={loading}
            />

            <ConfirmationPanel 
              selectedOption={selectedOption}
              orderId={orderId}
              idempotencyKey={idempotencyKey}
              setIdempotencyKey={setIdempotencyKey}
              onConfirm={handleConfirm}
              confirmationResult={confirmationResult}
              loading={loading}
            />
          </div>
        </div>
      </main>

      {/* Slide-over MCP Activity Trace Drawer with Real Protocol Logs */}
      <ActivityTraceDrawer 
        isOpen={isTraceOpen}
        onClose={() => setIsTraceOpen(false)}
        traceLogs={traceLogs}
        onClearLogs={() => setTraceLogs([])}
      />
    </div>
  );
}
