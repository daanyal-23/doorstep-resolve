import React from 'react';
import { Sparkles, CheckCircle2, Clock, AlertTriangle, XCircle, Zap } from 'lucide-react';

const SCENARIO_ICONS = {
  scenario_1: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
  scenario_2: <Clock className="w-3.5 h-3.5 text-amber-400" />,
  scenario_3: <XCircle className="w-3.5 h-3.5 text-rose-400" />,
  scenario_4: <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />,
  scenario_5: <Zap className="w-3.5 h-3.5 text-cyan-400" />,
};

const BADGE_STYLES = {
  emerald: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  amber: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  rose: "bg-rose-500/10 text-rose-300 border-rose-500/30",
  blue: "bg-blue-500/10 text-blue-300 border-blue-500/30",
};

export default function ScenarioPicker({ scenarios, activeScenarioId, onSelectScenario, loading }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4 mb-6 shadow-lg backdrop-blur-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-alexa-cyan" />
          <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider font-['Outfit']">
            Synthetic Business Scenarios (Hackathon Test Suite)
          </h2>
        </div>
        <span className="text-xs text-slate-400">
          Click any scenario to simulate order, inventory, cutoffs & deadlines
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5">
        {scenarios.map((sc) => {
          const isActive = activeScenarioId === sc.id;
          const badgeClass = BADGE_STYLES[sc.badge_color] || BADGE_STYLES.emerald;

          return (
            <button
              key={sc.id}
              onClick={() => onSelectScenario(sc)}
              disabled={loading}
              className={`flex flex-col text-left p-3 rounded-xl border transition-all duration-200 relative overflow-hidden group ${
                isActive
                  ? 'bg-slate-800/90 border-alexa-cyan shadow-[0_0_15px_rgba(0,200,255,0.25)] ring-1 ring-alexa-cyan/60'
                  : 'bg-slate-950/40 border-slate-800/80 hover:bg-slate-800/50 hover:border-slate-700'
              } ${loading ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'}`}
            >
              {isActive && (
                <div className="absolute top-0 right-0 w-12 h-12 bg-alexa-cyan/10 rounded-bl-full pointer-events-none" />
              )}
              
              <div className="flex items-center justify-between gap-1 mb-1.5">
                <span className="text-xs font-mono font-bold text-slate-300">
                  {sc.order_id}
                </span>
                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border flex items-center gap-1 ${badgeClass}`}>
                  {SCENARIO_ICONS[sc.id]}
                  {sc.badge}
                </span>
              </div>

              <div className="text-xs font-medium text-slate-100 group-hover:text-alexa-cyan transition-colors line-clamp-1 mb-1">
                {sc.title.split(":")[1] || sc.title}
              </div>

              <p className="text-[11px] text-slate-400 line-clamp-2 leading-relaxed">
                {sc.description}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
