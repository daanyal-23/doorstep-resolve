import React, { useState } from 'react';
import { History, ShieldCheck, CheckCircle2, RotateCcw, AlertTriangle, FileText, ChevronDown, ChevronUp } from 'lucide-react';

const EVENT_ICONS = {
  RESOLUTION_CONFIRMED: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
  IDEMPOTENT_RETRY_DETECTED: <RotateCcw className="w-4 h-4 text-blue-400" />,
  IDEMPOTENT_RETRY_BLOCKED: <RotateCcw className="w-4 h-4 text-blue-400" />,
  CONFIRMATION_REJECTED: <AlertTriangle className="w-4 h-4 text-rose-400" />,
  OPTIONS_CHECKED: <FileText className="w-4 h-4 text-alexa-cyan" />,
  DEFAULT: <FileText className="w-4 h-4 text-alexa-cyan" />,
};


export default function CaseHistoryTimeline({ events, onRefresh, loading }) {
  const [expandedEventId, setExpandedEventId] = useState(null);

  const toggleEvent = (idx) => {
    setExpandedEventId(expandedEventId === idx ? null : idx);
  };

  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 mb-6 shadow-md backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-alexa-cyan" />
          <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wider font-['Outfit']">
            Case Audit Trail (SQLite)
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-slate-400">
            {events?.length || 0} events
          </span>
          <button
            onClick={onRefresh}
            disabled={loading}
            className="text-[11px] text-alexa-cyan hover:underline disabled:opacity-50"
          >
            Refresh
          </button>
        </div>
      </div>

      {(!events || events.length === 0) ? (
        <div className="text-center py-6 text-slate-500 text-xs">
          No audit events recorded for this order yet.
        </div>
      ) : (
        <div className="relative pl-6 space-y-4 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
          {events.map((ev, idx) => {
            const isExpanded = expandedEventId === idx;
            const eventType = ev.event_type || ev.event_name || ev.type || 'AUDIT_EVENT';
            const icon = EVENT_ICONS[eventType] || EVENT_ICONS.DEFAULT;
            const rawDate = ev.timestamp || ev.created_at;
            const dateStr = rawDate ? new Date(rawDate).toLocaleString([], {
              month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'
            }) : 'Recorded';

            return (
              <div key={idx} className="relative group">
                {/* Timeline Dot */}
                <div className="absolute -left-6 top-1 w-5 h-5 rounded-full bg-slate-900 border border-slate-700 flex items-center justify-center">
                  <div className="w-2 h-2 rounded-full bg-alexa-cyan"></div>
                </div>

                <div className="bg-slate-950/60 rounded-xl p-3 border border-slate-800/80 hover:border-slate-700 transition">
                  <div className="flex items-center justify-between cursor-pointer" onClick={() => toggleEvent(idx)}>
                    <div className="flex items-center gap-2">
                      {icon}
                      <span className="text-xs font-bold font-mono text-slate-200">
                        {eventType}
                      </span>
                    </div>
                    <span className="text-[10px] text-slate-400 font-mono">
                      {dateStr}
                    </span>
                  </div>

                  {ev.case_id && (
                    <div className="text-[11px] text-slate-400 font-mono mt-1">
                      Case: <span className="text-slate-300">{ev.case_id}</span>
                    </div>
                  )}

                  {/* Expandable Details */}
                  {ev.details && Object.keys(ev.details).length > 0 && (
                    <div className="mt-2">
                      <button
                        type="button"
                        onClick={() => toggleEvent(idx)}
                        className="text-[10px] text-alexa-cyan flex items-center gap-1"
                      >
                        <span>{isExpanded ? 'Hide Payload' : 'View Event Payload'}</span>
                        {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                      </button>

                      {isExpanded && (
                        <pre className="mt-2 p-2 bg-slate-900 rounded-lg text-[10px] text-slate-300 font-mono overflow-x-auto border border-slate-800">
                          {JSON.stringify(ev.details, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
