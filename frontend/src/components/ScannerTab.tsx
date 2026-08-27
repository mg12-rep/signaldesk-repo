"use client";

import React, { useState, useEffect } from "react";

interface ScanResult {
  symbol: string;
  exchange: string;
  close: number;
  sma_50: number;
  sma_150: number;
  sma_200: number;
  rs_rating: number;
  stage_2_pass: boolean;
  signal_type: string;
}

export default function ScannerTab() {
  const [exchange, setExchange] = useState<"US" | "NSE" | "ALL">("US");
  const [strategy, setStrategy] = useState<string>("STAGE_2");
  const [results, setResults] = useState<ScanResult[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchScanResults = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `http://localhost:8000/api/v1/scanner/run?exchange=${exchange}&strategy=${strategy}`,
      );
      if (!res.ok) throw new Error("Failed to fetch scanner results");
      const data = await res.json();
      setResults(data);
    } catch (err: any) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchScanResults();
  }, [exchange, strategy]);

  return (
    <div className="p-6 bg-slate-900 text-white rounded-lg shadow-md">
      {/* Controls Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6 pb-4 border-b border-slate-800">
        <div>
          <h2 className="text-xl font-bold tracking-wide">Strategy Scanner</h2>
          <p className="text-sm text-slate-400">
            Live Stage 2 Trend Template & Momentum Screener
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Exchange Filter */}
          <select
            value={exchange}
            onChange={(e) => setExchange(e.target.value as any)}
            className="bg-slate-800 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="US">US Universe (S&P 500 / NASDAQ)</option>
            <option value="NSE">NSE 500</option>
            <option value="ALL">All Markets</option>
          </select>

          {/* Strategy Selector */}
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="bg-slate-800 border border-slate-700 text-sm rounded-md px-3 py-2 text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="STAGE_2">Minervini Stage 2 Breakout</option>
            <option value="CONNORS_RSI">Connors RSI Mean Reversion</option>
            <option value="MOMENTUM">Relative Strength Leader</option>
          </select>

          <button
            onClick={fetchScanResults}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded-md text-sm font-semibold transition disabled:opacity-50"
          >
            {loading ? "Scanning..." : "Run Scan"}
          </button>
        </div>
      </div>

      {/* Error Notice */}
      {error && (
        <div className="bg-red-900/40 border border-red-500 text-red-200 px-4 py-3 rounded mb-4 text-sm">
          {error}
        </div>
      )}

      {/* Dynamic Results Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-800 text-xs font-semibold uppercase text-slate-400 bg-slate-950/40">
              <th className="py-3 px-4">Symbol</th>
              <th className="py-3 px-4">Market</th>
              <th className="py-3 px-4">LTP</th>
              <th className="py-3 px-4">SMA 50</th>
              <th className="py-3 px-4">SMA 150</th>
              <th className="py-3 px-4">SMA 200</th>
              <th className="py-3 px-4">RS Score</th>
              <th className="py-3 px-4">Status</th>
              <th className="py-3 px-4 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 text-sm">
            {loading ? (
              <tr>
                <td colSpan={9} className="py-8 text-center text-slate-400">
                  Running quantitative filters across database...
                </td>
              </tr>
            ) : results.length === 0 ? (
              <tr>
                <td colSpan={9} className="py-8 text-center text-slate-500">
                  No stocks currently match the {strategy} criteria for{" "}
                  {exchange}.
                </td>
              </tr>
            ) : (
              results.map((row) => (
                <tr
                  key={row.symbol}
                  className="hover:bg-slate-800/50 transition"
                >
                  <td className="py-3 px-4 font-bold text-white">
                    {row.symbol}
                  </td>
                  <td className="py-3 px-4 text-slate-400">{row.exchange}</td>
                  <td className="py-3 px-4 font-medium">
                    ${row.close.toFixed(2)}
                  </td>
                  <td className="py-3 px-4 text-slate-300">
                    ${row.sma_50.toFixed(2)}
                  </td>
                  <td className="py-3 px-4 text-slate-300">
                    ${row.sma_150.toFixed(2)}
                  </td>
                  <td className="py-3 px-4 text-slate-300">
                    ${row.sma_200.toFixed(2)}
                  </td>
                  <td className="py-3 px-4 font-semibold text-emerald-400">
                    +{row.rs_rating}%
                  </td>
                  <td className="py-3 px-4">
                    <span className="bg-emerald-950 text-emerald-300 border border-emerald-800 text-xs px-2.5 py-0.5 rounded font-medium">
                      Stage 2 Valid
                    </span>
                  </td>
                  <td className="py-3 px-4 text-right">
                    <button className="bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium px-3 py-1.5 rounded border border-slate-700 transition">
                      Trade
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
