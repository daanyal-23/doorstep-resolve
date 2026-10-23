import React, { useState } from 'react';
import { Volume2, Sparkles, CheckCircle2, AlertOctagon, Send, Bot, ShieldAlert, Cpu } from 'lucide-react';

export default function AlexaAssistantCard({ 
  order, 
  resolutionResult, 
  customerDeadline,
  loading,
  error,
  agentMessage,
  providerName = 'deterministic-mock-test-provider',
  isMock = true,
  onSendQuery,
}) {
  const [inputQuery, setInputQuery] = useState('');

  const handleFormSubmit = (e) => {
    e.preventDefault();
    if (!inputQuery.trim() || loading) return;
    if (onSendQuery) {
      onSendQuery(inputQuery.trim());
    }
  };

  const handleChipClick = (suggestion) => {
    if (loading) return;
    setInputQuery(suggestion);
    if (onSendQuery) {
      onSendQuery(suggestion);
    }
  };

  const getFallbackMessage = () => {
    if (loading) {
      return "Agent orchestrating genuine MCP tools over Streamable HTTP...";
    }
    if (error) {
      return `Fulfillment evaluation encountered an issue: ${error}`;
    }
    if (!resolutionResult) {
      return "Welcome! Select a scenario above or ask a question to verify whether a replacement can provably meet your customer's deadline.";
    }

    const { meets_any_option, options } = resolutionResult;
    if (!order) return "Order details retrieved. Evaluating options...";

    const bestOption = options && options.length > 0 ? options[0] : null;

    if (!bestOption || !bestOption.is_eligible) {
      if (bestOption && bestOption.reason && bestOption.reason.toLowerCase().includes("window")) {
        return `I checked order ${order.order_id} (${order.item_name}). The 30-day replacement policy window has expired, so an automated replacement cannot be dispatched. Recorded audit event for escalation.`;
      }
      return `I checked regional inventory across fulfillment centers for ${order.item_name}. No replacement units are in stock. Rather than making an unfulfillable promise, this case is flagged immediately for alternative resolution.`;
    }

    if (meets_any_option && bestOption.meets_deadline) {
      const carrier = bestOption.carrier || 'FastTrack Logistics';
      const speed = (bestOption.shipping_speed || bestOption.shipping_method || 'Standard').replace('_', ' ');
      const arrival = bestOption.estimated_arrival ? new Date(bestOption.estimated_arrival).toLocaleString([], {
        weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
      }) : 'soon';
      const deadlineStr = new Date(customerDeadline).toLocaleString([], {
        weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
      });

      return `Good news! Stock verified at ${bestOption.warehouse_id}. Dispatched via ${carrier} (${speed}), replacement will arrive by ${arrival}—ahead of your ${deadlineStr} deadline. Review ranked options below to proceed.`;
    }

    if (!meets_any_option) {
      const earliestArrival = bestOption.estimated_arrival ? new Date(bestOption.estimated_arrival).toLocaleString([], {
        weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
      }) : 'past deadline';
      const deadlineStr = new Date(customerDeadline).toLocaleString([], {
        weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
      });

      return `Attention: Earliest possible arrival is ${earliestArrival}, which misses your ${deadlineStr} deadline due to dispatch cutoff times. To prevent broken promises, this arrival is flagged for customer review.`;
    }

    return "Evaluation completed. Please review the ranked options below.";
  };

  const isPositive = resolutionResult?.meets_any_option;
  const isNegative = resolutionResult && !resolutionResult.meets_any_option;

  const currentDisplayMessage = agentMessage || getFallbackMessage();

  return (
    <div className={`rounded-2xl p-4 sm:p-5 border mb-6 relative overflow-hidden backdrop-blur-md transition-all duration-300 ${
      isPositive 
        ? 'bg-gradient-to-r from-emerald-950/30 via-slate-900/50 to-slate-900/60 border-emerald-500/40 shadow-[0_0_20px_rgba(16,185,129,0.15)]'
        : isNegative
        ? 'bg-gradient-to-r from-amber-950/30 via-slate-900/50 to-slate-900/60 border-amber-500/40 shadow-[0_0_20px_rgba(245,158,11,0.15)]'
        : 'bg-gradient-to-r from-blue-950/30 via-slate-900/50 to-slate-900/60 border-alexa-cyan/30 shadow-[0_0_20px_rgba(0,200,255,0.1)]'
    }`}>
      {/* Top Section: Assistant Avatar & Speech Bubble */}
      <div className="flex items-start gap-4 mb-4">
        {/* Pulsing Avatar */}
        <div className={`p-2.5 rounded-xl border flex items-center justify-center shrink-0 mt-0.5 ${
          isPositive
            ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400'
            : isNegative
            ? 'bg-amber-500/20 border-amber-500/40 text-amber-400'
            : 'bg-alexa-cyan/20 border-alexa-cyan/40 text-alexa-cyan'
        }`}>
          {loading ? (
            <Bot className="w-5 h-5 animate-bounce" />
          ) : (
            <Volume2 className="w-5 h-5 animate-pulse" />
          )}
        </div>

        <div className="flex-1">
          {/* Header Row: Provider Badge & Status Flag */}
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-alexa-cyan font-['Outfit'] flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5" />
                Alexa+ Agent Orchestrator
              </span>

              {/* Provider Badge (Mock vs Live OpenAI) */}
              <span
                className={`text-[10px] font-mono px-2 py-0.5 rounded-full flex items-center gap-1 border ${
                  isMock
                    ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                    : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                }`}
                title={
                  isMock
                    ? 'Offline deterministic testing provider. No external LLM credits consumed.'
                    : `Live LLM Provider: ${providerName}`
                }
              >
                <Cpu className="w-2.5 h-2.5" />
                {isMock ? `Mock Provider: ${providerName}` : `Live Provider: ${providerName}`}
              </span>
            </div>

            {resolutionResult && (
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border flex items-center gap-1 ${
                isPositive 
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' 
                  : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
              }`}>
                {isPositive ? <CheckCircle2 className="w-3 h-3" /> : <AlertOctagon className="w-3 h-3" />}
                {isPositive ? 'Feasible & Safe' : 'Deadline Risk Flagged'}
              </span>
            )}
          </div>

          {/* Assistant Narrative */}
          <div className="bg-slate-950/40 rounded-xl p-3 border border-slate-800/80">
            <p className="text-sm sm:text-base text-slate-200 leading-relaxed font-normal">
              "{currentDisplayMessage}"
            </p>
          </div>
        </div>
      </div>

      {/* Interactive Conversational Input Form */}
      <form onSubmit={handleFormSubmit} className="pt-2 border-t border-slate-800/60">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={inputQuery}
            onChange={(e) => setInputQuery(e.target.value)}
            disabled={loading}
            placeholder={`Ask Alexa+ agent about ${order?.order_id || 'this order'} (e.g. "Check replacement options for ${order?.order_id || 'ORD-1001'} with deadline Friday")...`}
            className="flex-1 bg-slate-950/80 border border-slate-800 rounded-xl px-3.5 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-alexa-cyan/60 transition disabled:opacity-50 font-sans"
          />
          <button
            type="submit"
            disabled={loading || !inputQuery.trim()}
            className="bg-alexa-cyan hover:bg-cyan-400 text-slate-950 font-bold px-3.5 py-2 rounded-xl text-xs flex items-center gap-1.5 transition disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_0_12px_rgba(0,200,255,0.2)]"
          >
            {loading ? (
              <span className="w-4 h-4 border-2 border-slate-950 border-t-transparent rounded-full animate-spin" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
            <span className="hidden sm:inline">Ask Agent</span>
          </button>
        </div>

        {/* Suggestion Chips */}
        <div className="flex flex-wrap items-center gap-2 mt-2.5">
          <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Quick Prompts:</span>
          {[
            `Check replacement options for ${order?.order_id || 'ORD-1001'}`,
            `Investigate case history for ${order?.order_id || 'ORD-1001'}`,
            `Lookup policy details for ${order?.order_id || 'ORD-1001'}`,
          ].map((prompt, idx) => (
            <button
              key={idx}
              type="button"
              disabled={loading}
              onClick={() => handleChipClick(prompt)}
              className="bg-slate-800/70 hover:bg-slate-700/80 text-slate-300 border border-slate-700/60 rounded-lg px-2.5 py-0.5 text-[11px] transition hover:border-alexa-cyan/40 disabled:opacity-40"
            >
              {prompt}
            </button>
          ))}
        </div>
      </form>
    </div>
  );
}
