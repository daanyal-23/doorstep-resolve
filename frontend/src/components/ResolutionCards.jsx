import React, { useState } from 'react';
import { 
  CheckCircle2, 
  AlertTriangle, 
  XCircle, 
  Truck, 
  Clock, 
  ChevronDown, 
  ChevronUp, 
  Warehouse, 
  ShieldAlert,
  Sparkles,
  ArrowRight
} from 'lucide-react';

export default function ResolutionCards({ 
  options, 
  selectedOptionId, 
  onSelectOption, 
  customerDeadline,
  loading 
}) {
  const [expandedEvidence, setExpandedEvidence] = useState({});

  const toggleEvidence = (optionId) => {
    setExpandedEvidence(prev => ({
      ...prev,
      [optionId]: !prev[optionId]
    }));
  };

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2].map((i) => (
          <div key={i} className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 animate-pulse">
            <div className="h-4 bg-slate-800 rounded w-1/4 mb-3"></div>
            <div className="h-6 bg-slate-800 rounded w-3/4 mb-3"></div>
            <div className="h-3 bg-slate-800 rounded w-1/2"></div>
          </div>
        ))}
      </div>
    );
  }

  if (!options || options.length === 0) {
    return (
      <div className="bg-slate-900/40 border border-slate-800/80 rounded-2xl p-8 text-center text-slate-400">
        <Truck className="w-10 h-10 mx-auto mb-3 opacity-30 text-slate-500" />
        <h4 className="text-base font-semibold text-slate-300 mb-1">No Resolution Options Found</h4>
        <p className="text-xs text-slate-500">
          Check order ID and simulation parameters to generate feasibility estimates.
        </p>
      </div>
    );
  }

  // Partition outcomes deterministically
  const feasibleOptions = options.filter(opt => opt.is_eligible && opt.meets_deadline);
  const deadlineMissingOptions = options.filter(opt => opt.is_eligible && !opt.meets_deadline);
  const ineligibleOptions = options.filter(opt => !opt.is_eligible);

  const deadlineDate = customerDeadline ? new Date(customerDeadline) : null;
  const formattedDeadline = deadlineDate ? deadlineDate.toLocaleString([], {
    weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  }) : customerDeadline;

  const allMissDeadline = feasibleOptions.length === 0 && deadlineMissingOptions.length > 0;
  const allIneligible = feasibleOptions.length === 0 && deadlineMissingOptions.length === 0;

  const renderCard = (opt, { rankLabel, isFallback, isBlocked, isTopFeasible }) => {
    const isSelected = selectedOptionId === opt.option_id;
    const isEligible = opt.is_eligible;
    const meetsDeadline = opt.meets_deadline;
    const isExpanded = !!expandedEvidence[opt.option_id];

    const arrivalDate = opt.estimated_arrival ? new Date(opt.estimated_arrival) : null;
    let deltaHours = null;
    if (arrivalDate && deadlineDate) {
      deltaHours = ((deadlineDate - arrivalDate) / (1000 * 60 * 60)).toFixed(1);
    }

    let cardStyle = "bg-slate-900/60 border-slate-800 hover:border-slate-700";
    let badgeStyle = "bg-slate-800 text-slate-400 border-slate-700";

    if (isEligible && meetsDeadline) {
      cardStyle = isSelected
        ? "bg-slate-900/90 border-emerald-400 ring-2 ring-emerald-500/50 shadow-[0_0_25px_rgba(16,185,129,0.25)]"
        : "bg-slate-900/70 border-emerald-500/40 hover:border-emerald-500/80 shadow-[0_0_15px_rgba(16,185,129,0.1)]";
      badgeStyle = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
    } else if (isEligible && !meetsDeadline) {
      cardStyle = isSelected
        ? "bg-slate-900/90 border-amber-400 ring-2 ring-amber-500/50 shadow-[0_0_25px_rgba(245,158,11,0.25)]"
        : "bg-slate-900/70 border-amber-500/40 hover:border-amber-500/80 shadow-[0_0_15px_rgba(245,158,11,0.1)]";
      badgeStyle = "bg-amber-500/20 text-amber-300 border-amber-500/40";
    } else {
      cardStyle = "bg-slate-950/50 border-rose-900/30";
      badgeStyle = "bg-rose-500/10 text-rose-300 border-rose-500/30";
    }

    return (
      <div
        key={opt.option_id}
        className={`rounded-2xl border p-5 transition-all duration-200 relative ${cardStyle}`}
      >
        {/* Header Badges */}
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            {/* Rank / Outcome badge */}
            {!isBlocked && (
              <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded border ${
                isFallback
                  ? 'bg-amber-950/60 text-amber-300 border-amber-600/40'
                  : 'bg-slate-800 text-slate-300 border-slate-700'
              }`}>
                {rankLabel}
              </span>
            )}

            {isBlocked && (
              <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-0.5 rounded border bg-rose-950/50 text-rose-300 border-rose-700/50">
                <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
                <span>Blocked Outcome</span>
              </span>
            )}

            {isTopFeasible && (
              <span className="flex items-center gap-1 text-[11px] font-semibold text-alexa-cyan bg-alexa-cyan/10 border border-alexa-cyan/30 px-2 py-0.5 rounded-full">
                <Sparkles className="w-3 h-3" />
                Recommended Match
              </span>
            )}

            {isFallback && allMissDeadline && (
              <span className="text-[11px] font-medium text-amber-400 bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 rounded-full">
                Least-Bad Fallback
              </span>
            )}
          </div>

          {/* Status Badge */}
          <div className={`text-xs font-semibold px-2.5 py-1 rounded-full border flex items-center gap-1.5 ${badgeStyle}`}>
            {isEligible && meetsDeadline && (
              <>
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                <span>SAFE PROMISE: MEETS DEADLINE</span>
              </>
            )}
            {isEligible && !meetsDeadline && (
              <>
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                <span>HIGH RISK: MISSES DEADLINE</span>
              </>
            )}
            {!isEligible && (
              <>
                <XCircle className="w-3.5 h-3.5 text-rose-400" />
                <span>INELIGIBLE</span>
              </>
            )}
          </div>
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-3">
          {/* Warehouse & Shipping */}
          <div className="sm:col-span-1">
            <div className="text-xs text-slate-400 mb-0.5">Fulfillment Route</div>
            <div className="text-sm font-semibold text-slate-100 flex items-center gap-1.5">
              <Warehouse className="w-4 h-4 text-blue-400" />
              <span>{opt.warehouse_id || "No Location"}</span>
            </div>
            <div className="text-xs text-slate-300 mt-1 flex items-center gap-1">
              <Truck className="w-3.5 h-3.5 text-slate-400" />
              <span className="font-medium">{opt.carrier || "No Carrier"}</span>
              {opt.shipping_speed && (
                <span className="text-slate-500 font-mono text-[11px]">
                  ({opt.shipping_speed.replace('_', ' ')})
                </span>
              )}
            </div>
          </div>

          {/* Arrival & Deadline Buffer */}
          <div className="sm:col-span-1">
            <div className="text-xs text-slate-400 mb-0.5">Estimated Arrival</div>
            <div className="text-sm font-mono font-semibold text-slate-100">
              {arrivalDate ? arrivalDate.toLocaleString([], {
                weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
              }) : 'No Route / No ETA'}
            </div>
            {deltaHours !== null && (
              <div className={`text-xs font-medium mt-1 flex items-center gap-1 ${
                meetsDeadline ? 'text-emerald-400' : 'text-amber-400'
              }`}>
                <Clock className="w-3.5 h-3.5" />
                <span>
                  {meetsDeadline 
                    ? `+${deltaHours} hrs buffer before deadline`
                    : `${Math.abs(deltaHours)} hrs PAST deadline`
                  }
                </span>
              </div>
            )}
          </div>

          {/* Cost & Selection Action */}
          <div className="sm:col-span-1 flex flex-col justify-between items-start sm:items-end">
            <div>
              <div className="text-xs text-slate-400 mb-0.5 sm:text-right">Fulfillment Cost</div>
              <div className="text-sm font-semibold text-slate-100 sm:text-right">
                ${opt.cost ? opt.cost.toFixed(2) : "0.00"}
              </div>
            </div>

            {/* Selection Action */}
            {isEligible ? (
              <button
                type="button"
                onClick={() => onSelectOption(opt)}
                className={`mt-2 px-3 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition ${
                  isSelected
                    ? 'bg-alexa-cyan text-slate-950 shadow-[0_0_12px_rgba(0,200,255,0.4)]'
                    : isFallback
                    ? 'bg-slate-800 hover:bg-amber-950/40 text-amber-200 border border-amber-600/30'
                    : 'bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700'
                }`}
              >
                <span>{isSelected ? 'Selected' : isFallback ? 'Select Fallback' : 'Select Option'}</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            ) : (
              <span className="text-[11px] text-rose-300 bg-rose-950/40 border border-rose-800/40 px-2.5 py-1 rounded-lg mt-2 font-medium">
                {opt.reason || "Fulfillment Blocked"}
              </span>
            )}
          </div>
        </div>

        {/* Ineligible Specific Reason Alert */}
        {isBlocked && opt.reason && (
          <div className="bg-rose-950/30 border border-rose-800/40 rounded-xl p-2.5 text-xs text-rose-200 flex items-start gap-2 mb-2">
            <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-rose-300">Root Cause: </span>
              {opt.reason}
            </div>
          </div>
        )}

        {/* Supporting Evidence Accordion */}
        {opt.evidence && opt.evidence.length > 0 && (
          <div className="mt-3 pt-3 border-t border-slate-800/80">
            <button
              type="button"
              onClick={() => toggleEvidence(opt.option_id)}
              className="flex items-center justify-between w-full text-xs text-slate-400 hover:text-slate-200 py-1"
            >
              <span className="font-medium flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-alexa-cyan" />
                <span>Supporting Decision Evidence ({opt.evidence.length} steps)</span>
              </span>
              {isExpanded ? (
                <ChevronUp className="w-4 h-4 text-slate-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-slate-400" />
              )}
            </button>

            {isExpanded && (
              <div className="mt-2 space-y-1.5 bg-slate-950/70 rounded-xl p-3 border border-slate-800/80 text-xs font-mono">
                {opt.evidence.map((step, sIdx) => (
                  <div key={sIdx} className="flex items-start gap-2 text-slate-300">
                    <span className="text-alexa-cyan font-bold select-none">{sIdx + 1}.</span>
                    <span className="leading-relaxed">{step}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* Top Banner when ALL available options miss deadline */}
      {allMissDeadline && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-2xl p-4 text-amber-200 shadow-lg">
          <div className="flex items-center gap-2 font-semibold text-sm text-amber-300">
            <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />
            <span>No Delivery Option Meets Customer Deadline</span>
          </div>
          <p className="text-xs text-amber-200/90 mt-1.5 leading-relaxed">
            Every evaluated delivery route arrives after the required deadline ({formattedDeadline}). 
            The option(s) shown below are least-bad fallbacks and are NOT safe recommendations. 
            Explicit customer agreement is required before confirming any late delivery.
          </p>
        </div>
      )}

      {/* Top Banner when ALL options are ineligible */}
      {allIneligible && (
        <div className="bg-rose-500/10 border border-rose-500/30 rounded-2xl p-4 text-rose-200 shadow-lg">
          <div className="flex items-center gap-2 font-semibold text-sm text-rose-300">
            <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
            <span>Replacement Request Blocked</span>
          </div>
          <p className="text-xs text-rose-200/90 mt-1.5 leading-relaxed">
            No fulfillment routes can be scheduled due to policy or inventory constraints. Review the blocked reasons below for escalation details.
          </p>
        </div>
      )}

      {/* Group 1: Feasible Options */}
      {feasibleOptions.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wider font-['Outfit'] flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>Feasible Resolution Options ({feasibleOptions.length})</span>
            </h3>
            <span className="text-xs text-emerald-400 font-medium">
              Meets deadline before {formattedDeadline}
            </span>
          </div>
          <div className="space-y-3">
            {feasibleOptions.map((opt, idx) =>
              renderCard(opt, {
                rankLabel: `Rank #${idx + 1}`,
                isFallback: false,
                isBlocked: false,
                isTopFeasible: idx === 0,
              })
            )}
          </div>
        </div>
      )}

      {/* Group 2: Deadline-Missing Options */}
      {deadlineMissingOptions.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-amber-300 uppercase tracking-wider font-['Outfit'] flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              <span>
                {allMissDeadline
                  ? `Least-Bad Fallback Options (${deadlineMissingOptions.length})`
                  : `Alternative Options (Misses Deadline) (${deadlineMissingOptions.length})`}
              </span>
            </h3>
            <span className="text-xs text-amber-400/80">
              {allMissDeadline ? "All routes arrive after deadline" : "Arrives after required deadline"}
            </span>
          </div>
          <div className="space-y-3">
            {deadlineMissingOptions.map((opt, idx) =>
              renderCard(opt, {
                rankLabel: allMissDeadline ? `Fallback #${idx + 1}` : `Alt #${idx + 1} (Late)`,
                isFallback: true,
                isBlocked: false,
                isTopFeasible: false,
              })
            )}
          </div>
        </div>
      )}

      {/* Group 3: Ineligible / Blocked Outcomes */}
      {ineligibleOptions.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-rose-300 uppercase tracking-wider font-['Outfit'] flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 text-rose-400" />
              <span>Blocked / Ineligible Outcomes ({ineligibleOptions.length})</span>
            </h3>
            <span className="text-xs text-rose-400/80">
              Action blocked by policy or stock
            </span>
          </div>
          <div className="space-y-3">
            {ineligibleOptions.map((opt) =>
              renderCard(opt, {
                rankLabel: "",
                isFallback: false,
                isBlocked: true,
                isTopFeasible: false,
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
