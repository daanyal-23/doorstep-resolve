import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  CheckCircle2, 
  AlertCircle, 
  Copy, 
  RefreshCw, 
  RotateCcw, 
  Truck, 
  Lock,
  FileCheck,
  AlertTriangle
} from 'lucide-react';

export default function ConfirmationPanel({
  selectedOption,
  orderId,
  idempotencyKey,
  setIdempotencyKey,
  onConfirm,
  confirmationResult,
  loading
}) {
  const [customerAgreed, setCustomerAgreed] = useState(false);
  const [customerNotes, setCustomerNotes] = useState("Customer requested immediate fulfillment test.");
  const [copiedKey, setCopiedKey] = useState(false);

  useEffect(() => {
    // For safe feasible options, default agreement to true; for deadline-missing fallbacks, require explicit opt-in
    if (selectedOption && selectedOption.meets_deadline) {
      setCustomerAgreed(true);
    } else {
      setCustomerAgreed(false);
    }
  }, [selectedOption?.option_id]);

  // Synchronize idempotency key when orderId changes to prevent leaking prior order token
  useEffect(() => {
    if (orderId && (!idempotencyKey || !idempotencyKey.includes(orderId))) {
      setIdempotencyKey(`IDEM-${orderId}-${Math.random().toString(36).substring(2, 6).toUpperCase()}`);
    }
  }, [orderId]);

  const generateNewKey = () => {
    const newKey = `IDEM-${orderId || 'ORD'}-${Math.random().toString(36).substring(2, 6).toUpperCase()}`;
    setIdempotencyKey(newKey);
  };

  const copyKey = () => {
    navigator.clipboard.writeText(idempotencyKey);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 2000);
  };

  const handleTestRejected = () => {
    const freshKey = `IDEM-REJECT-${orderId || 'ORD'}-${Math.random().toString(36).substring(2, 6).toUpperCase()}`;
    setIdempotencyKey(freshKey);
    onConfirm({
      customerAgreed: false,
      customerNotes: "Testing rejected agreement",
      overrideKey: freshKey,
    });
  };

  // If selectedOption belongs to a different order, prevent displaying mismatched target
  const isOptionValidForOrder = selectedOption && (!selectedOption.order_id || selectedOption.order_id === orderId);

  if (!selectedOption || !isOptionValidForOrder) {
    return (
      <div className="bg-slate-900/40 border border-slate-800/80 rounded-2xl p-6 text-center text-slate-500 mb-6">
        <ShieldCheck className="w-8 h-8 mx-auto mb-2 opacity-30" />
        <h4 className="text-sm font-semibold text-slate-300">Select an Option to Confirm</h4>
        <p className="text-xs text-slate-500 mt-1">
          No option is selected by default to prevent accidental fulfillment commitments. Pick a feasible option or manually select a fallback option above to review and confirm.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 mb-6 shadow-xl backdrop-blur-md">
      <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-5 h-5 text-alexa-cyan" />
          <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wider font-['Outfit']">
            Explicit Resolution Confirmation
          </h3>
        </div>
        <span className="text-[11px] font-mono text-slate-400 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
          Step 2 of 2
        </span>
      </div>

      {/* Confirmation Form */}
      <div className="space-y-4">
        {/* Selected Option Summary Banner */}
        <div className="bg-slate-950/60 rounded-xl p-3 border border-slate-800 flex items-center justify-between">
          <div>
            <div className="text-[11px] text-slate-400">Target Resolution:</div>
            <div className="text-xs font-mono font-semibold text-slate-200">
              {selectedOption.option_id}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">
              Route: <span className="text-slate-300">{selectedOption.warehouse_id}</span> via <span className="text-slate-300">{selectedOption.carrier}</span> ({selectedOption.shipping_speed})
            </div>
          </div>
          <div className="text-right">
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
              selectedOption.meets_deadline
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
            }`}>
              {selectedOption.meets_deadline ? 'Meets Deadline' : 'Late Arrival (Misses Deadline)'}
            </span>
          </div>
        </div>

        {/* Infeasible / Deadline-Missing Warning */}
        {!selectedOption.meets_deadline && (
          <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-3 text-amber-200 text-xs flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <span className="font-semibold text-amber-300">Explicit Customer Consent Required: </span>
              <p className="text-amber-200/90 leading-relaxed">
                This option arrives after the requested deadline. It is provided strictly as a least-bad fallback. The customer must explicitly acknowledge and approve the late delivery before recording this resolution.
              </p>
            </div>
          </div>
        )}

        {/* Idempotency Key Bar */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs font-medium text-slate-300 flex items-center gap-1.5">
              <Lock className="w-3.5 h-3.5 text-alexa-cyan" />
              <span>Idempotency Token (Replay Protection):</span>
            </label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={copyKey}
                className="text-[10px] text-slate-400 hover:text-slate-200 flex items-center gap-1"
              >
                <Copy className="w-3 h-3" />
                <span>{copiedKey ? 'Copied!' : 'Copy'}</span>
              </button>
              <button
                type="button"
                onClick={generateNewKey}
                className="text-[10px] text-alexa-cyan hover:underline flex items-center gap-1"
              >
                <RefreshCw className="w-3 h-3" />
                <span>New Token</span>
              </button>
            </div>
          </div>
          <input
            type="text"
            value={idempotencyKey}
            onChange={(e) => setIdempotencyKey(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 font-mono focus:outline-none focus:border-alexa-cyan"
            placeholder="e.g. IDEM-12345678"
          />
          <p className="text-[10px] text-slate-500 mt-1">
            Re-submitting with this token tests backend idempotency: identical requests will not duplicate fulfillment actions.
          </p>
        </div>

        {/* Explicit Customer Agreement Checkbox */}
        <div className="bg-slate-950/40 rounded-xl p-3 border border-slate-800/80">
          <label className="flex items-start gap-2.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={customerAgreed}
              onChange={(e) => setCustomerAgreed(e.target.checked)}
              className="mt-0.5 rounded border-slate-700 text-alexa-cyan focus:ring-alexa-cyan/40 bg-slate-900 w-4 h-4 cursor-pointer"
            />
            <div className="text-xs">
              <span className="font-semibold text-slate-200">
                Explicit Customer Agreement (Policy Requirement)
              </span>
              <p className="text-slate-400 mt-0.5">
                The customer explicitly authorized this resolution after reviewing delivery feasibility and schedule constraints.
              </p>
            </div>
          </label>
        </div>

        {/* Customer Notes */}
        <div>
          <label className="text-xs font-medium text-slate-300 block mb-1">
            Resolution Notes (Persisted to Audit Log):
          </label>
          <input
            type="text"
            value={customerNotes}
            onChange={(e) => setCustomerNotes(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 focus:outline-none focus:border-alexa-cyan"
            placeholder="Notes regarding customer conversation..."
          />
        </div>

        {/* Action Buttons */}
        <div className="flex flex-col sm:flex-row items-center gap-2 pt-2">
          <button
            type="button"
            onClick={() => onConfirm({ customerAgreed, customerNotes })}
            disabled={loading}
            className="w-full sm:flex-1 bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-slate-950 font-semibold py-2.5 px-4 rounded-xl text-xs sm:text-sm transition-all shadow-[0_0_15px_rgba(16,185,129,0.3)] hover:shadow-[0_0_20px_rgba(16,185,129,0.5)] flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <CheckCircle2 className="w-4 h-4" />
            <span>{loading ? 'Recording Resolution...' : 'Confirm Simulated Resolution'}</span>
          </button>

          <button
            type="button"
            onClick={handleTestRejected}
            disabled={loading}
            className="w-full sm:w-auto bg-slate-800 hover:bg-slate-700 text-rose-300 border border-rose-500/30 font-medium py-2.5 px-3 rounded-xl text-xs transition flex items-center justify-center gap-1.5"
            title="Sends request without customer agreement to verify policy guardrail"
          >
            <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
            <span>Test Rejected Flow</span>
          </button>
        </div>
      </div>

      {/* Confirmation Result Receipt */}
      {confirmationResult && (!confirmationResult.resolution || !confirmationResult.resolution.order_id || confirmationResult.resolution.order_id === orderId) && (
        <div className={`mt-5 pt-4 border-t rounded-xl p-4 transition-all ${
          confirmationResult.status === 'CONFIRMED'
            ? 'bg-emerald-950/40 border-emerald-500/40'
            : confirmationResult.status === 'ALREADY_CONFIRMED'
            ? 'bg-blue-950/40 border-blue-500/40'
            : 'bg-rose-950/40 border-rose-500/40'
        }`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold uppercase tracking-wider flex items-center gap-1.5 font-['Outfit']">
              {confirmationResult.status === 'CONFIRMED' && (
                <>
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  <span className="text-emerald-300">Simulated Fulfillment Recorded</span>
                </>
              )}
              {confirmationResult.status === 'ALREADY_CONFIRMED' && (
                <>
                  <RotateCcw className="w-4 h-4 text-blue-400" />
                  <span className="text-blue-300">Idempotent Replay Verified (Duplicate Prevented)</span>
                </>
              )}
              {confirmationResult.status === 'CONFIRMATION_REQUIRED' && (
                <>
                  <AlertCircle className="w-4 h-4 text-rose-400" />
                  <span className="text-rose-300">Policy Block: Explicit Agreement Required</span>
                </>
              )}
            </span>

            <span className="text-[10px] font-mono text-slate-400">
              {confirmationResult.idempotent_replay ? 'Replay: TRUE' : 'Replay: FALSE'}
            </span>
          </div>

          {confirmationResult.simulated_fulfillment && (
            <div className="bg-slate-950/60 rounded-lg p-2.5 text-xs font-mono space-y-1 mb-2 border border-slate-800">
              <div className="text-slate-300">
                Tracking ID: <span className="text-alexa-cyan font-bold">{confirmationResult.simulated_fulfillment.simulated_tracking_id}</span>
              </div>
              <div className="text-[11px] text-slate-400">
                Notice: {confirmationResult.simulated_fulfillment.notice}
              </div>
            </div>
          )}

          {confirmationResult.message && (
            <p className="text-xs text-slate-300 mb-1">{confirmationResult.message}</p>
          )}

          {confirmationResult.error && (
            <p className="text-xs text-rose-300 mb-1">{confirmationResult.error}</p>
          )}
        </div>
      )}
    </div>
  );
}
