"use client";

import React, { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  RefreshCw,
  ShieldCheck,
  AlertTriangle,
  Eye,
  Send,
  Zap,
  TrendingUp,
} from "lucide-react";

interface SignalItem {
  status: string;
  ticker: string;
  date: string;
  trigger_price: number;
  trailing_stop?: number;
  atr14?: number;
  close: number;
  volume: number;
  rs_rank?: number;
  swing_high?: number;
  fill_price_est?: number;
  hard_stop?: number;
  suggested_shares?: number;
  suggested_cost?: number;
  volume_needed?: number;
  pct_from_trigger?: number;
  base_age_days?: number;
}

interface ScannerRunResponse {
  strategy: string;
  mode: string;
  market_label: string;
  market_status: "HEALTHY" | "UNHEALTHY" | string;
  total_universe_count: number;
  scanned_count: number;
  buy_today: SignalItem[];
  near_buys: SignalItem[];
  watchlist: SignalItem[];
}

function ResultsContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [data, setData] = useState<ScannerRunResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<
    "BUY_TODAY" | "NEAR_BUYS" | "WATCHLIST"
  >("BUY_TODAY");
  const [selectedSignal, setSelectedSignal] = useState<SignalItem | null>(null);

  const fetchSignals = async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `http://localhost:8000/api/v1/scanner/run?${searchParams.toString()}`,
      );
      if (res.ok) {
        const json: ScannerRunResponse = await res.json();
        setData(json);
        if (json.buy_today.length > 0) {
          setSelectedSignal(json.buy_today[0]);
          setActiveTab("BUY_TODAY");
        } else if (json.near_buys.length > 0) {
          setSelectedSignal(json.near_buys[0]);
          setActiveTab("NEAR_BUYS");
        } else if (json.watchlist.length > 0) {
          setSelectedSignal(json.watchlist[0]);
          setActiveTab("WATCHLIST");
        } else {
          setSelectedSignal(null);
        }
      }
    } catch (err) {
      console.error("Failed to execute scanner:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSignals();
  }, [searchParams]);

  const currentList =
    activeTab === "BUY_TODAY"
      ? data?.buy_today || []
      : activeTab === "NEAR_BUYS"
        ? data?.near_buys || []
        : data?.watchlist || [];

  return (
    <div className="space-y-6 p-1">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push("/scanner")}
            className="p-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white transition"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-white tracking-tight">
                Signal Scanner Results
              </h1>
              <span className="bg-slate-800 text-slate-300 text-[10px] font-mono px-2 py-0.5 rounded">
                {data?.market_label}
              </span>
              <span
                className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                  data?.market_status === "HEALTHY"
                    ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                    : "bg-rose-950 text-rose-400 border border-rose-800"
                }`}
              >
                REGIME: {data?.market_status}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Scanned {data?.scanned_count || 0} stocks (from{" "}
              {data?.total_universe_count || 0} universe constituents)
            </p>
          </div>
        </div>

        <button
          onClick={fetchSignals}
          disabled={loading}
          className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 px-3 py-1.5 rounded-md text-xs font-medium transition"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 text-emerald-400 ${loading ? "animate-spin" : ""}`}
          />
          <span>Rerun Scan</span>
        </button>
      </div>

      {/* Signal Type Tabs */}
      <div className="flex gap-2 border-b border-slate-800 pb-2">
        <button
          onClick={() => {
            setActiveTab("BUY_TODAY");
            setSelectedSignal(data?.buy_today[0] || null);
          }}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold transition ${
            activeTab === "BUY_TODAY"
              ? "bg-emerald-950 text-emerald-300 border border-emerald-700"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Zap className="h-3.5 w-3.5" />
          <span>BUY TODAY ({data?.buy_today.length || 0})</span>
        </button>

        <button
          onClick={() => {
            setActiveTab("NEAR_BUYS");
            setSelectedSignal(data?.near_buys[0] || null);
          }}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold transition ${
            activeTab === "NEAR_BUYS"
              ? "bg-amber-950 text-amber-300 border border-amber-700"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <AlertTriangle className="h-3.5 w-3.5" />
          <span>Volume Pending ({data?.near_buys.length || 0})</span>
        </button>

        <button
          onClick={() => {
            setActiveTab("WATCHLIST");
            setSelectedSignal(data?.watchlist[0] || null);
          }}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold transition ${
            activeTab === "WATCHLIST"
              ? "bg-blue-950 text-blue-300 border border-blue-700"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Eye className="h-3.5 w-3.5" />
          <span>Active Watchlist ({data?.watchlist.length || 0})</span>
        </button>
      </div>

      {/* Main Grid: Signal Table & Trade Staging */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Table View */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800/80 rounded-xl overflow-hidden shadow-xl">
          <div className="overflow-x-auto">
            {/* Replace the <table> inside page.tsx with this updated structure */}
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-[11px] font-semibold text-slate-400 uppercase tracking-wider bg-slate-950/40">
                  <th className="py-3 px-4">Ticker</th>
                  <th className="py-3 px-3">Close</th>
                  <th className="py-3 px-3">Trigger / Base</th>
                  <th className="py-3 px-3">MRS Rank</th>
                  <th className="py-3 px-3">Dist SMA %</th>
                  <th className="py-3 px-3 text-rose-400">Hard Stop (8%)</th>
                  <th className="py-3 px-3 text-amber-400">
                    Trailing SL (2×ATR)
                  </th>
                  <th className="py-3 px-3 text-slate-400">ATR(14W)</th>
                  <th className="py-3 px-3 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-xs">
                {loading ? (
                  <tr>
                    <td
                      colSpan={9}
                      className="py-12 text-center text-slate-500 font-mono"
                    >
                      Scanning ETF universe...
                    </td>
                  </tr>
                ) : currentList.length === 0 ? (
                  <tr>
                    <td
                      colSpan={9}
                      className="py-12 text-center text-slate-500 font-mono"
                    >
                      No setups in this category.
                    </td>
                  </tr>
                ) : (
                  currentList.map((item) => {
                    const isSelected = selectedSignal?.ticker === item.ticker;
                    return (
                      <tr
                        key={item.ticker}
                        onClick={() => setSelectedSignal(item)}
                        className={`hover:bg-slate-800/40 cursor-pointer transition ${
                          isSelected ? "bg-slate-800/60" : ""
                        }`}
                      >
                        <td className="py-3 px-4 font-bold text-white font-mono">
                          {item.ticker}
                        </td>
                        <td className="py-3 px-3 font-mono text-slate-200">
                          ${item.close.toFixed(2)}
                        </td>
                        <td className="py-3 px-3 font-mono text-emerald-400 font-semibold">
                          ${item.trigger_price.toFixed(2)}
                        </td>
                        <td
                          className={`py-3 px-3 font-mono font-semibold ${
                            (item.rs_rank ?? 0) >= 0
                              ? "text-purple-300"
                              : "text-amber-400"
                          }`}
                        >
                          {item.rs_rank !== undefined && item.rs_rank !== null
                            ? item.rs_rank.toFixed(1)
                            : "—"}
                        </td>
                        <td className="py-3 px-3 font-mono text-slate-400">
                          +
                          {item.pct_from_trigger
                            ? item.pct_from_trigger.toFixed(1)
                            : "0.0"}
                          %
                        </td>
                        <td className="py-3 px-3 font-mono text-rose-400 font-semibold">
                          $
                          {item.hard_stop
                            ? item.hard_stop.toFixed(2)
                            : (item.close * 0.92).toFixed(2)}
                        </td>
                        <td className="py-3 px-3 font-mono text-amber-400 font-semibold">
                          {item.trailing_stop
                            ? `$${item.trailing_stop.toFixed(2)}`
                            : "—"}
                        </td>
                        <td className="py-3 px-3 font-mono text-slate-400">
                          {item.atr14 ? `$${item.atr14.toFixed(2)}` : "—"}
                        </td>
                        <td className="py-3 px-3 text-right">
                          <span
                            className={`text-[10px] px-2 py-0.5 rounded font-bold ${
                              item.status === "BUY_TODAY"
                                ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                                : "bg-blue-950 text-blue-400 border border-blue-800"
                            }`}
                          >
                            {item.status}
                          </span>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Trade Execution / Staging Ticket */}
        <div className="bg-slate-900 border border-slate-800/80 rounded-xl p-5 space-y-4 shadow-xl">
          <div className="border-b border-slate-800 pb-3 flex justify-between items-center">
            <h2 className="text-sm font-bold text-white">
              Order Staging Ticket
            </h2>
            <span className="text-[11px] font-mono text-emerald-400">
              {selectedSignal ? selectedSignal.ticker : "None Selected"}
            </span>
          </div>

          {selectedSignal ? (
            <div className="space-y-4">
              {/* Trigger Price Card */}
              <div className="bg-slate-950 p-2.5 rounded border border-slate-800">
                <span className="text-slate-500 text-[10px] block">
                  Trigger Price
                </span>
                <span className="font-mono text-white font-bold text-sm">
                  ${selectedSignal.trigger_price.toFixed(2)}
                </span>
              </div>

              {/* Stop Loss Cards: Hard Stop vs 2xATR Trailing Stop */}
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-slate-950/70 p-3 rounded-lg border border-slate-800">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider">
                    Hard Stop (8%)
                  </div>
                  <span className="font-mono text-rose-400 font-bold text-sm">
                    $
                    {selectedSignal.hard_stop !== undefined &&
                    selectedSignal.hard_stop !== null
                      ? selectedSignal.hard_stop.toFixed(2)
                      : (selectedSignal.trigger_price * 0.92).toFixed(2)}
                  </span>
                </div>

                <div className="bg-slate-950/70 p-3 rounded-lg border border-slate-800">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider">
                    Trailing Stop (2×ATR)
                  </div>
                  <span className="font-mono text-amber-400 font-bold text-sm">
                    {selectedSignal.trailing_stop !== undefined &&
                    selectedSignal.trailing_stop !== null
                      ? `$${selectedSignal.trailing_stop.toFixed(2)}`
                      : "N/A"}
                  </span>
                  {selectedSignal.atr14 !== undefined &&
                    selectedSignal.atr14 !== null && (
                      <div className="text-[9px] text-slate-500 font-mono mt-0.5">
                        ATR: ${selectedSignal.atr14.toFixed(2)}
                      </div>
                    )}
                </div>
              </div>

              {selectedSignal.suggested_shares ? (
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="bg-slate-950 p-2.5 rounded border border-slate-800">
                    <span className="text-slate-500 text-[10px] block">
                      Calculated Shares
                    </span>
                    <span className="font-mono text-emerald-400 font-bold">
                      {selectedSignal.suggested_shares}
                    </span>
                  </div>
                  <div className="bg-slate-950 p-2.5 rounded border border-slate-800">
                    <span className="text-slate-500 text-[10px] block">
                      Position Sizing
                    </span>
                    <span className="font-mono text-slate-200 font-bold">
                      ₹{selectedSignal.suggested_cost?.toLocaleString()}
                    </span>
                  </div>
                </div>
              ) : null}

              <div className="space-y-2 text-xs">
                <label className="text-slate-400">Broker Execution Desk</label>
                <div className="grid grid-cols-3 gap-2">
                  {["ZERODHA", "UPSTOX", "IBKR"].map((broker) => (
                    <button
                      key={broker}
                      className="py-1.5 text-center rounded border border-slate-800 text-[10px] font-bold text-slate-300 hover:border-emerald-500 hover:text-emerald-400 transition"
                    >
                      {broker}
                    </button>
                  ))}
                </div>
              </div>

              <button
                onClick={() =>
                  alert(`Staging buy ticket for ${selectedSignal.ticker}`)
                }
                className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs py-2.5 rounded-lg shadow-lg transition"
              >
                <Send className="h-3.5 w-3.5" />
                <span>Stage Order Ticket</span>
              </button>
            </div>
          ) : (
            <div className="py-16 text-center text-slate-500 text-xs">
              Select a ticker from the table to view order parameters and stage
              trade tickets.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ResultsPage() {
  return (
    <Suspense
      fallback={
        <div className="p-6 text-slate-500 font-mono">
          Loading signal desk...
        </div>
      }
    >
      <ResultsContent />
    </Suspense>
  );
}
