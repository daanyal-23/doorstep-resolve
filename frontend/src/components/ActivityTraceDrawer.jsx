import React, { useState } from 'react';
import { X, Terminal, Clock, CheckCircle2, AlertCircle, Copy, Trash2, ArrowUpRight } from 'lucide-react';

export default function ActivityTraceDrawer({ isOpen, onClose, traceLogs, onClearLogs }) {
  const [selectedLogIndex, setSelectedLogIndex] = useState(0);

  if (!isOpen) return null;

  const activeLog = traceLogs && traceLogs.length > 0 ? traceLogs[selectedLogIndex] : null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm transition-opacity">
      <div className="w-full max-w-2xl bg-[#0d1424] border-l border-slate-800 h-full flex flex-col shadow-2xl animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/90">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-alexa-cyan/10 border border-alexa-cyan/30 rounded-lg text-alexa-cyan">
              <Terminal className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-100 font-['Outfit']">
                MCP Activity Trace & Tool Protocol Logs
              </h3>
              <p className="text-xs text-slate-400">
                Real-time Streamable HTTP tool calls & responses
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onClearLogs}
              className="p-1.5 text-slate-400 hover:text-rose-400 transition"
              title="Clear Logs"
            >
              <Trash2 className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-100 transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content area: Split into List (Top/Left) & Detail (Bottom/Right) */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {(!traceLogs || traceLogs.length === 0) ? (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-slate-500 text-sm">
              <Terminal className="w-10 h-10 mb-2 opacity-30 text-slate-400" />
              <p>No MCP tool calls recorded yet.</p>
              <p className="text-xs text-slate-600 mt-1">
                Interact with the scenarios or re-evaluate options to see live tool calls.
              </p>
            </div>
          ) : (
            <>
              {/* Call List */}
              <div className="h-48 border-b border-slate-800 overflow-y-auto divide-y divide-slate-800/60 bg-slate-950/40">
                {traceLogs.map((log, idx) => {
                  const isSelected = selectedLogIndex === idx;
                  const isError = log.status === 'ERROR' || log.status === 'NOT_FOUND';

                  return (
                    <div
                      key={idx}
                      onClick={() => setSelectedLogIndex(idx)}
                      className={`p-3 text-xs cursor-pointer flex items-center justify-between transition ${
                        isSelected 
                          ? 'bg-slate-800/80 border-l-2 border-alexa-cyan' 
                          : 'hover:bg-slate-900/50'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {isError ? (
                          <AlertCircle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                        ) : (
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                        )}
                        <span className="font-mono font-bold text-slate-200">
                          {log.tool}
                        </span>
                      </div>

                      <div className="flex items-center gap-2 text-[11px] font-mono text-slate-400">
                        <span className="text-alexa-cyan font-semibold">
                          {log.durationMs}ms
                        </span>
                        <span>{log.timestamp}</span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Selected Call Detail */}
              {activeLog && (
                <div className="flex-1 overflow-y-auto p-4 space-y-4 font-mono text-xs">
                  {/* Summary row */}
                  <div className="bg-slate-900 rounded-xl p-3 border border-slate-800 flex items-center justify-between">
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase">Invoked Tool</div>
                      <div className="text-sm font-bold text-alexa-cyan">{activeLog.tool}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase">Execution Latency</div>
                      <div className="text-sm font-bold text-slate-200">{activeLog.durationMs} ms</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase">Status</div>
                      <div className="text-xs font-bold text-emerald-400">{activeLog.status || 'OK'}</div>
                    </div>
                  </div>

                  {/* Arguments JSON */}
                  <div>
                    <div className="flex items-center justify-between text-[11px] text-slate-400 mb-1 font-sans font-semibold">
                      <span>Tool Arguments:</span>
                    </div>
                    <pre className="bg-slate-950 p-3 rounded-xl border border-slate-800 text-slate-300 overflow-x-auto text-[11px]">
                      {JSON.stringify(activeLog.arguments, null, 2)}
                    </pre>
                  </div>

                  {/* Response JSON */}
                  <div>
                    <div className="flex items-center justify-between text-[11px] text-slate-400 mb-1 font-sans font-semibold">
                      <span>Structured Tool Response:</span>
                    </div>
                    <pre className="bg-slate-950 p-3 rounded-xl border border-slate-800 text-emerald-300/90 overflow-x-auto text-[11px]">
                      {JSON.stringify(activeLog.response, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
