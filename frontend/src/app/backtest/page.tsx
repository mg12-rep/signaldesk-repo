"use client";

import React, { useState, useEffect } from "react";
import {
  Play,
  BarChart3,
  Settings2,
  Loader2,
  TrendingUp,
  TrendingDown,
} from "lucide-react";

export default function BacktestStudio() {
  const [strategy, setStrategy] = useState("minervini");
  const [universe, setUniverse] = useState("NIFTY500");
  const [startingCapital, setStartingCapital] = useState(1000000);
  const [params, setParams] = useState<Record<string, any>>({});
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [errorMsg, setErrorMsg] = useState("");

  // Load config whenever strategy OR universe changes
  useEffect(() => {
    async function loadConfig() {
      setLoadingConfig(true);
      setErrorMsg("");
      try {
        const res = await fetch(
          `http://127.0.0.1:8000/api/v1/backtest/config/${strategy}?universe=${universe}`,
        );
        if (!res.ok) {
          const errData = await res.json();
          throw new Error(
            errData.detail || "Failed to load strategy configuration.",
          );
        }
        const data = await res.json();
        setParams(data.params || {});
        if (data.starting_capital) {
          setStartingCapital(data.starting_capital);
        }
      } catch (err: any) {
        setErrorMsg(err.message || "Failed loading configuration.");
      } finally {
        setLoadingConfig(false);
      }
    }
    loadConfig();
  }, [strategy, universe]);

  const handleParamChange = (key: string, val: string) => {
    setParams((prev) => ({
      ...prev,
      [key]: val,
    }));
  };

  const handleRunSimulation = async () => {
    setSimulating(true);
    setErrorMsg("");

    // Convert string inputs to proper types
    const parsedParams: Record<string, any> = {};
    for (const [key, val] of Object.entries(params)) {
      if (val === "true" || val === true) {
        parsedParams[key] = true;
      } else if (val === "false" || val === false) {
        parsedParams[key] = false;
      } else if (val === "" || val === "null" || val === null) {
        parsedParams[key] = null;
      } else if (typeof val === "string") {
        try {
          // Parses JSON arrays like profit_targets: [[0.2, 0.5]] or valid numbers
          parsedParams[key] = JSON.parse(val);
        } catch {
          parsedParams[key] = isNaN(Number(val)) ? val : Number(val);
        }
      } else {
        parsedParams[key] = val;
      }
    }

    try {
      const res = await fetch(`http://127.0.0.1:8000/api/v1/backtest/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy,
          universe,
          starting_capital: Number(startingCapital),
          params: parsedParams,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Simulation execution failed.");
      }
      const data = await res.json();
      setResults(data);
    } catch (err: any) {
      setErrorMsg(err.message || "An error occurred during simulation.");
    } finally {
      setSimulating(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-8 max-w-6xl mx-auto">
      <h1 className="text-xl font-bold text-white mb-1 flex items-center gap-2">
        <BarChart3 className="h-6 w-6 text-emerald-400" /> Backtest Studio
      </h1>
      <p className="text-slate-400 text-sm mb-6">
        Historical parameter simulation with cash sweep, portfolio tracking, and
        regime gating.
      </p>

      {errorMsg && (
        <div className="mb-4 p-3 bg-rose-950/40 border border-rose-800 text-rose-300 rounded text-xs">
          {errorMsg}
        </div>
      )}

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 mb-4 grid grid-cols-1 md:grid-cols-3 gap-4">
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
            <option value="mean_rev">Mean Reversion-BB-OBV</option>
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

        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-1.5">
            Starting Capital
          </label>
          <input
            type="number"
            value={startingCapital}
            onChange={(e) =>
              setStartingCapital(parseFloat(e.target.value) || 0)
            }
            className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-xs text-white"
          />
        </div>
      </div>

      <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-5 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <Settings2 className="h-4 w-4 text-slate-400" />
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Model Configuration Parameters
          </h2>
        </div>

        {loadingConfig ? (
          <div className="text-xs text-slate-500 flex items-center gap-2 py-4">
            <Loader2 className="h-4 w-4 animate-spin text-emerald-400" />{" "}
            Loading configuration...
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Object.entries(params).map(([k, v]) => (
              <div key={k}>
                <label
                  className="block text-[11px] text-slate-400 mb-1 truncate"
                  title={k}
                >
                  {k.replace(/_/g, " ")}
                </label>
                <input
                  type="text"
                  value={v ?? ""}
                  onChange={(e) => handleParamChange(k, e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded p-1.5 text-xs text-white"
                />
              </div>
            ))}
          </div>
        )}

        <div className="mt-4 flex justify-end">
          <button
            disabled={simulating || loadingConfig}
            onClick={handleRunSimulation}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold text-xs px-6 py-2.5 rounded flex items-center justify-center gap-2 transition"
          >
            {simulating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            {simulating ? "Simulating Strategy..." : "Run Simulation"}
          </button>
        </div>
      </div>

      {results && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
              <div className="text-xs text-slate-500">CAGR</div>
              <div className="text-xl font-bold text-emerald-400 mt-1">
                {(results.stats.cagr_pct ?? 0).toFixed(1)}%
              </div>
            </div>
            <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
              <div className="text-xs text-slate-500">Position Win Rate</div>
              <div className="text-xl font-bold text-white mt-1">
                {(results.stats.position_win_rate_pct ?? 0).toFixed(1)}%
              </div>
            </div>
            <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
              <div className="text-xs text-slate-500">Profit Factor</div>
              <div className="text-xl font-bold text-white mt-1">
                {(results.stats.profit_factor ?? 0).toFixed(2)}
              </div>
            </div>
            <div className="bg-slate-900 border border-slate-800 p-4 rounded-lg">
              <div className="text-xs text-slate-500">Max Drawdown</div>
              <div className="text-xl font-bold text-rose-400 mt-1">
                {(results.stats.max_drawdown_pct ?? 0).toFixed(1)}%
              </div>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800 flex justify-between items-center">
              <span className="text-xs font-semibold text-slate-300">
                Executed Trades ({results.recentTrades?.length || 0})
              </span>
              <span className="text-xs text-slate-500">
                Total Account: ₹
                {results.stats.total_account_value?.toLocaleString()}
              </span>
            </div>
            <div className="overflow-x-auto max-h-80">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-950 text-slate-500 uppercase text-[10px] sticky top-0">
                  <tr>
                    <th className="p-2.5">Ticker</th>
                    <th className="p-2.5">Entry Date</th>
                    <th className="p-2.5">Entry Price</th>
                    <th className="p-2.5">Shares</th>
                    <th className="p-2.5">Exit Date</th>
                    <th className="p-2.5">Exit Price</th>
                    <th className="p-2.5">Exit Reason</th>
                    <th className="p-2.5 text-right">PnL %</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {results.recentTrades?.map((t: any, i: number) => {
                    const isPositive = t.pnlPct >= 0;
                    return (
                      <tr key={i} className="hover:bg-slate-800/40">
                        <td className="p-2.5 font-semibold text-white">
                          {t.ticker}
                        </td>
                        <td className="p-2.5">{t.entryDate}</td>
                        <td className="p-2.5">₹{t.entryPrice}</td>
                        <td className="p-2.5">{t.shares}</td>
                        <td className="p-2.5">{t.exitDate}</td>
                        <td className="p-2.5">₹{t.exitPrice}</td>
                        <td className="p-2.5 text-slate-400">{t.exitReason}</td>
                        <td
                          className={`p-2.5 text-right font-medium flex items-center justify-end gap-1 ${isPositive ? "text-emerald-400" : "text-rose-400"}`}
                        >
                          {isPositive ? (
                            <TrendingUp className="h-3 w-3" />
                          ) : (
                            <TrendingDown className="h-3 w-3" />
                          )}
                          {t.pnlPct}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
