import React from 'react';
import { ShieldCheck, Activity, Terminal, Sparkles, CheckCircle2 } from 'lucide-react';

export default function Header({ toolCallsCount, onOpenTrace, backendConnected }) {
  return (
    <header className="border-b border-slate-800 bg-[#0d1424]/80 backdrop-blur-md sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-20 flex items-center justify-between">
        {/* Brand & Alexa+ Avatar */}
        <div className="flex items-center gap-4">
          <div className="relative flex items-center justify-center">
            {/* Pulsing ring animation */}
            <div className="w-12 h-12 rounded-full bg-gradient-to-tr from-alexa-cyan via-blue-500 to-indigo-600 animate-spin opacity-80 blur-xs" style={{ animationDuration: '6s' }}></div>
            <div className="absolute w-10 h-10 rounded-full bg-[#0b0f19] flex items-center justify-center border border-alexa-cyan/60 shadow-[0_0_15px_rgba(0,200,255,0.4)]">
              <Sparkles className="w-5 h-5 text-alexa-cyan animate-pulse" />
            </div>
            <div className="absolute -bottom-1 -right-1 w-3.5 h-3.5 bg-emerald-500 rounded-full border-2 border-[#0b0f19]" title="Agent Engine Online"></div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight text-white font-['Outfit']">
                Doorstep Resolve
              </h1>
              <span className="bg-gradient-to-r from-alexa-cyan/20 to-blue-500/20 text-alexa-cyan border border-alexa-cyan/30 text-[11px] font-semibold px-2 py-0.5 rounded-full">
                Alexa+ Agent
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Autonomous Delivery Feasibility & Resolution Engine
            </p>
          </div>
        </div>

        {/* Status Indicators & Activity Trace Button */}
        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-2 bg-slate-900/90 border border-slate-800 px-3 py-1.5 rounded-lg text-xs">
            <span className={`w-2 h-2 rounded-full ${backendConnected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-500'}`} />
            <span className="text-slate-300 font-medium">
              {backendConnected ? 'MCP Server (Streamable HTTP)' : 'Connecting...'}
            </span>
            <span className="text-slate-600">|</span>
            <span className="text-slate-400">4 Tools Active</span>
          </div>

          <button
            onClick={onOpenTrace}
            className="flex items-center gap-2 bg-slate-800/80 hover:bg-slate-700/80 text-slate-200 border border-slate-700/80 px-3.5 py-2 rounded-xl text-xs font-medium transition-all duration-200 hover:border-alexa-cyan/50 hover:shadow-[0_0_12px_rgba(0,200,255,0.2)]"
          >
            <Terminal className="w-4 h-4 text-alexa-cyan" />
            <span>MCP Activity Trace</span>
            {toolCallsCount > 0 && (
              <span className="bg-alexa-cyan text-slate-950 font-bold px-1.5 py-0.2 rounded-full text-[10px]">
                {toolCallsCount}
              </span>
            )}
          </button>
        </div>
      </div>
    </header>
  );
}
