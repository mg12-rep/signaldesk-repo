"use client";

import React, { useState } from "react";
import { Play, Settings2, FileSpreadsheet, Layers } from "lucide-react";

export default function StrategyRunner() {
  const [strategy, setStrategy] = useState("minervini");
  const [universe, setUniverse] = useState("NSE_500");
  const [customFile, setCustomFile] = useState(
    "C:/Work/SignalDesk/data/evergreen_filter_stocks.csv",
  );
  const [isRunning, setIsRunning] = useState(false);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-8 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold text-white mb-1 flex items-center gap-2">
        <Settings2 className="h-6 w-6 text-emerald-400" /> Strategy Scanner
      </h1>
      <p className="text-slate-400 text-sm mb-6">
        Select parameters and launch real-time scans against the database.
      </p>

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6 space-y-6">
        {/* Strategy Selector */}
        <div>
          <label className="block text-sm font-semibold text-slate-300 mb-2">
            Strategy Model
          </label>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-md p-2.5 text-sm text-white focus:ring-1 focus:ring-emerald-500 outline-none"
          >
            <option value="minervini">Minervini Stage-2 VCP Breakout</option>
            <option value="connors">Larry Connors 2-Period RSI Pullback</option>
          </select>
        </div>

        {/* Universe Selector */}
        <div>
          <label className="block text-sm font-semibold text-slate-300 mb-2 flex items-center gap-1.5">
            <Layers className="h-4 w-4 text-emerald-400" /> Target Universe
          </label>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { id: "NSE_500", label: "NSE 500" },
              { id: "NSE_ALL", label: "NSE (All Stocks)" },
              { id: "SNP_500", label: "S&P 500" },
              { id: "NASDAQ_100", label: "NASDAQ 100" },
            ].map((u) => (
              <button
                key={u.id}
                type="button"
                onClick={() => setUniverse(u.id)}
                className={`py-2.5 px-3 rounded-md text-xs font-semibold border text-center transition ${
                  universe === u.id
                    ? "bg-emerald-950 border-emerald-600 text-emerald-300"
                    : "bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700"
                }`}
              >
                {u.label}
              </button>
            ))}
          </div>
        </div>

        {/* Custom Stock Filter List */}
        <div>
          <label className="block text-sm font-semibold text-slate-300 mb-2 flex items-center gap-1.5">
            <FileSpreadsheet className="h-4 w-4 text-emerald-400" /> Custom
            Shortlist / Filter (Optional)
          </label>
          <input
            type="text"
            value={customFile}
            onChange={(e) => setCustomFile(e.target.value)}
            placeholder="File path to .csv or leave blank"
            className="w-full bg-slate-950 border border-slate-700 rounded-md p-2.5 text-xs text-slate-300 outline-none"
          />
        </div>

        {/* Run Button */}
        <div className="pt-4 border-t border-slate-800 flex justify-end">
          <button
            onClick={() => {
              setIsRunning(true);
              setTimeout(() => {
                setIsRunning(false);
                window.location.href = "/results";
              }, 1200);
            }}
            disabled={isRunning}
            className="bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-sm px-6 py-2.5 rounded-md flex items-center gap-2 transition disabled:opacity-50"
          >
            <Play className={`h-4 w-4 ${isRunning ? "animate-spin" : ""}`} />
            {isRunning ? "Scanning Database..." : "Run Scanner"}
          </button>
        </div>
      </div>
    </div>
  );
}
