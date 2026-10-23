import React from 'react';
import { Clock, RefreshCw, Zap, Sliders } from 'lucide-react';

export default function DeadlineControl({
  customerDeadline,
  setCustomerDeadline,
  currentTime,
  setCurrentTime,
  onEvaluate,
  loading
}) {
  const addHoursToDeadline = (hours) => {
    try {
      const base = new Date(customerDeadline);
      base.setHours(base.getHours() + hours);
      // Format as YYYY-MM-DDTHH:mm
      const iso = base.toISOString().slice(0, 16);
      setCustomerDeadline(iso);
    } catch (e) {
      console.error(e);
    }
  };

  const advanceCutoffTest = () => {
    // Toggles current time between 10:00 (before cutoff) and 18:00 (after cutoff)
    try {
      const cur = new Date(currentTime);
      if (cur.getHours() < 17) {
        cur.setHours(18, 0, 0, 0); // After cutoff
      } else {
        cur.setHours(10, 0, 0, 0); // Before cutoff
      }
      setCurrentTime(cur.toISOString().slice(0, 16));
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 mb-6 shadow-md backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-alexa-cyan" />
          <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wider font-['Outfit']">
            Deadline & Simulation Controls
          </h3>
        </div>
        <span className="text-[11px] text-slate-400">
          Deterministic Cutoff Engine
        </span>
      </div>

      <div className="space-y-4">
        {/* Customer Deadline Input */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs font-medium text-slate-300">
              Customer Required Deadline:
            </label>
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-slate-400">Quick adjust:</span>
              <button
                type="button"
                onClick={() => addHoursToDeadline(12)}
                className="text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded border border-slate-700 transition"
              >
                +12h
              </button>
              <button
                type="button"
                onClick={() => addHoursToDeadline(24)}
                className="text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded border border-slate-700 transition"
              >
                +24h
              </button>
              <button
                type="button"
                onClick={() => addHoursToDeadline(-12)}
                className="text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded border border-slate-700 transition"
              >
                -12h
              </button>
            </div>
          </div>
          <input
            type="datetime-local"
            value={customerDeadline ? customerDeadline.slice(0, 16) : ""}
            onChange={(e) => setCustomerDeadline(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-alexa-cyan focus:ring-1 focus:ring-alexa-cyan"
          />
        </div>

        {/* Current Simulated Time Input */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs font-medium text-slate-300 flex items-center gap-1.5">
              <span>Simulated Order / Request Time:</span>
            </label>
            <button
              type="button"
              onClick={advanceCutoffTest}
              className="text-[10px] text-alexa-cyan hover:underline flex items-center gap-1"
              title="Toggle between before cutoff (10:00) and after cutoff (18:00)"
            >
              <Zap className="w-3 h-3" />
              Toggle Cutoff (10:00 ↔ 18:00)
            </button>
          </div>
          <input
            type="datetime-local"
            value={currentTime ? currentTime.slice(0, 16) : ""}
            onChange={(e) => setCurrentTime(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-alexa-cyan focus:ring-1 focus:ring-alexa-cyan"
          />
          <div className="text-[10px] text-slate-500 mt-1">
            Standard warehouse dispatch cutoff: 17:00 (5:00 PM). Orders after cutoff dispatch next morning.
          </div>
        </div>

        {/* Evaluate Button */}
        <button
          onClick={onEvaluate}
          disabled={loading}
          className="w-full bg-gradient-to-r from-alexa-cyan to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-semibold py-2.5 px-4 rounded-xl text-sm transition-all shadow-[0_0_15px_rgba(0,200,255,0.3)] hover:shadow-[0_0_25px_rgba(0,200,255,0.5)] flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          <span>{loading ? 'Evaluating Feasibility...' : 'Prove Feasibility & Rank Options'}</span>
        </button>
      </div>
    </div>
  );
}
