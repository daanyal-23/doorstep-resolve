import React from 'react';
import { Package, Calendar, DollarSign, MapPin, ShieldCheck, AlertCircle, Clock } from 'lucide-react';

export default function OrderCard({ order, loading, currentTime, resolutionResult }) {
  if (loading) {
    return (
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 animate-pulse mb-6">
        <div className="h-4 bg-slate-800 rounded w-1/3 mb-4"></div>
        <div className="h-6 bg-slate-800 rounded w-2/3 mb-4"></div>
        <div className="space-y-2">
          <div className="h-3 bg-slate-800 rounded w-full"></div>
          <div className="h-3 bg-slate-800 rounded w-5/6"></div>
        </div>
      </div>
    );
  }

  if (!order) {
    return (
      <div className="bg-slate-900/40 border border-slate-800/80 rounded-2xl p-6 text-center text-slate-500 mb-6">
        <Package className="w-8 h-8 mx-auto mb-2 opacity-40" />
        <p className="text-sm">No order selected</p>
      </div>
    );
  }

  const { order_id, item_id, price, delivered_at, policy, destination_address } = order;
  const windowDays = policy?.return_window_days ?? order?.return_window_days ?? 30;

  // Evaluate policy eligibility authoritatively from deterministic resolver & order policy
  const topActionType = resolutionResult?.options?.[0]?.action_type;
  const policyStatus = policy?.status || resolutionResult?.policy_evaluation?.status;

  // Evaluate date constraint against simulated/current time
  let isWindowExpiredByDate = false;
  if (delivered_at) {
    const deliveredTime = new Date(delivered_at).getTime();
    const evalTime = currentTime ? new Date(currentTime).getTime() : Date.now();
    const windowMs = windowDays * 24 * 60 * 60 * 1000;
    if (evalTime > deliveredTime + windowMs) {
      isWindowExpiredByDate = true;
    }
  }

  const isWindowExpired = 
    topActionType === 'REPLACEMENT_WINDOW_EXPIRED' ||
    policyStatus === 'WINDOW_EXPIRED' ||
    policy?.is_within_window === false ||
    isWindowExpiredByDate;

  const isPolicyDisallowed = 
    topActionType === 'REPLACEMENT_DISALLOWED' ||
    policyStatus === 'POLICY_DISALLOWED' ||
    (policy?.replacement_allowed === false && !isWindowExpired) ||
    (order?.replacement_allowed === 0 && !isWindowExpired);

  let badgeLabel = 'Replacements Eligible';
  let badgeEligible = true;

  if (isWindowExpired) {
    badgeLabel = 'Replacement Window Expired';
    badgeEligible = false;
  } else if (isPolicyDisallowed) {
    badgeLabel = 'Policy Blocked';
    badgeEligible = false;
  } else {
    badgeLabel = 'Replacements Eligible';
    badgeEligible = true;
  }

  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 mb-6 shadow-md backdrop-blur-sm">
      <div className="flex items-center justify-between mb-3 border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2">
          <Package className="w-4 h-4 text-alexa-cyan" />
          <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wider font-['Outfit']">
            Order & Policy Context
          </h3>
        </div>
        <span className="font-mono text-xs bg-slate-800 text-slate-300 px-2 py-0.5 rounded border border-slate-700">
          {order_id}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Product & Price */}
        <div>
          <div className="text-xs text-slate-400 mb-0.5">Purchased Item</div>
          <div className="text-sm font-semibold text-slate-100 flex items-center gap-1.5">
            <span>{item_id}</span>
          </div>
          <div className="text-xs text-slate-400 mt-1 flex items-center gap-1">
            <DollarSign className="w-3 h-3 text-emerald-400" />
            <span className="text-slate-200 font-medium">${price ? price.toFixed(2) : "0.00"}</span>
            <span className="text-slate-500">(1 unit)</span>
          </div>
        </div>

        {/* Delivery Timestamp */}
        <div>
          <div className="text-xs text-slate-400 mb-0.5">Delivered On</div>
          <div className="text-xs font-mono text-slate-200 flex items-center gap-1.5">
            <Calendar className="w-3.5 h-3.5 text-blue-400" />
            {delivered_at ? new Date(delivered_at).toLocaleDateString([], {
              year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
            }) : 'Unknown'}
          </div>
          <div className="text-[11px] text-slate-400 mt-1 flex items-center gap-1">
            <MapPin className="w-3 h-3 text-slate-500" />
            <span className="truncate">{destination_address || "Customer Residence"}</span>
          </div>
        </div>
      </div>

      {/* Policy Eligibility Banner */}
      <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-alexa-cyan" />
          <span className="text-slate-400">Policy:</span>
          <span className="text-slate-200 font-medium">
            {windowDays}-Day Replacement Window
          </span>
        </div>
        <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-semibold border ${
          badgeEligible
            ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
            : 'bg-rose-500/10 text-rose-300 border-rose-500/30'
        }`}>
          {badgeLabel}
        </span>
      </div>
    </div>
  );
}
