"use client";

import React, { useState } from "react";
import { Play, BarChart3, LineChart } from "lucide-react";

export default function BacktestStudio() {
  const [strategy, setStrategy] = useState("minervini");
  const [universe, setUniverse] = useState("NIFTY500");
  const [simulated, setSimulated] = useState(false);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-8 max-w-5xl mx-auto">
      <h1 className="text-xl font-bold text-white mb-1 flex items-center gap-2">
        <BarChart3 className="h-6 w-6 text-emerald-400" /> Backtest Studio
      </h1>
      <p className="text-slate-400 text-sm mb-6">
        Historical parameter simulation with cash sweep and regime gating.
      </p>

      {/* Inputs */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 mb-6 grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-1.5">
            Strategy Model
          </label>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-xs text-white"
          >
            <option value="minervini">Minervini Stage-2 VCP</option>
            <option value="connors">Larry Connors RSI(2) Pullback</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-1.5">
            Stock Universe
          </label>
          <select
            value={universe}
            onChange={(e) => setUniverse(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-xs text-white"
          >
            <option value="NIFTY500">NIFTY 500 (Constituents)</option>
            <option value="SP500">S&P 500 (Constituents)</option>
            <option value="NASDAQ100">NASDAQ 100</option>
          </select>
        </div>
        <div className="flex items-end">
          <button
            onClick={() => setSimulated(true)}
            className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs py-2.5 rounded flex items-center justify-center gap-1.5 transition"
          >
            <Play className="h-3.5 w-3.5" /> Run Simulation
          </button>
        </div>
      </div>

      {/* Simulated Results View */}
      {simulated && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
              <div className="text-xs text-slate-500">CAGR</div>
              <div className="text-xl font-bold text-emerald-400 mt-1">
                21.8%
              </div>
            </div>
            <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
              <div className="text-xs text-slate-500">Win Rate</div>
              <div className="text-xl font-bold text-white mt-1">42.5%</div>
            </div>
            <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
              <div className="text-xs text-slate-500">Profit Factor</div>
              <div className="text-xl font-bold text-white mt-1">2.14</div>
            </div>
            <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
              <div className="text-xs text-slate-500">Max Drawdown</div>
              <div className="text-xl font-bold text-rose-400 mt-1">-11.2%</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
