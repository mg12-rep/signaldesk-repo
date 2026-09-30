"use client";

import React, { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  RefreshCw,
  AlertTriangle,
  Eye,
  Send,
  Zap,
  BarChart2,
} from "lucide-react";
import Elder75mChartModal from "@/components/Elder75mChartModal";

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
  stage?: string;
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

  // Modal State
  const [chartModalSymbol, setChartModalSymbol] = useState<string | null>(null);

  const market = (searchParams.get("market") || "US").toUpperCase() as
    | "NSE"
    | "US";
  const currencySymbol = market === "NSE" ? "₹" : "$";

  const [syncing, setSyncing] = useState(false);

  // Sync only the tickers currently visible in the active tab/table
  const handleSyncDisplayed = async () => {
    if (!currentList.length) return;
    setSyncing(true);

    const symbols = Array.from(new Set(currentList.map((item) => item.ticker)));

    try {
      const res = await fetch(
        "/api/v1/sync/intraday-symbols",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbols, market }),
        },
      );

      if (!res.ok) {
        console.error("Fast sync failed:", await res.text());
      }
    } catch (err) {
      console.error("Error triggering fast sync:", err);
    } finally {
      setSyncing(false);
    }
  };

  const fetchSignals = async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `/api/v1/scanner/run?${searchParams.toString()}`,
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
                  data?.market_status === "HEALTHY" ||
                  data?.market_status === "STRONG"
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

        <div className="flex items-center gap-2">
          <button
            onClick={handleSyncDisplayed}
            disabled={syncing || loading || currentList.length === 0}
            className="flex items-center gap-1.5 bg-cyan-950 hover:bg-cyan-900 text-cyan-300 border border-cyan-800 px-3 py-1.5 rounded-md text-xs font-medium transition disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 text-cyan-400 ${syncing ? "animate-spin" : ""}`}
            />
            <span>
              {syncing
                ? "Syncing 15m..."
                : `Sync Displayed (${currentList.length})`}
            </span>
          </button>

          <button
            onClick={fetchSignals}
            disabled={loading || syncing}
            className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 px-3 py-1.5 rounded-md text-xs font-medium transition disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 text-emerald-400 ${loading ? "animate-spin" : ""}`}
            />
            <span>Rerun Scan</span>
          </button>
        </div>
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

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Table View */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800/80 rounded-xl overflow-hidden shadow-xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-[11px] font-semibold text-slate-400 uppercase tracking-wider bg-slate-950/40">
                  <th className="py-3 px-4">Ticker</th>
                  <th className="py-3 px-2 text-center">Chart</th>
                  <th className="py-3 px-3">Close</th>
                  <th className="py-3 px-3">Trigger / Base</th>
                  <th className="py-3 px-3">MRS / Stage</th>
                  <th className="py-3 px-3">Dist SMA %</th>
                  <th className="py-3 px-3 text-rose-400">Hard Stop</th>
                  <th className="py-3 px-3 text-amber-400">Trailing Stop</th>
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
                      Running multi-timeframe scanner...
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
                        <td className="py-3 px-2 text-center">
                          <button
                            title="View 75m RGB Chart"
                            onClick={(e) => {
                              e.stopPropagation();
                              setChartModalSymbol(item.ticker);
                            }}
                            className="p-1.5 rounded-md bg-slate-800 hover:bg-cyan-950 text-slate-400 hover:text-cyan-300 border border-slate-700 hover:border-cyan-700 transition"
                          >
                            <BarChart2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                        <td className="py-3 px-3 font-mono text-slate-200">
                          {currencySymbol}
                          {item.close.toFixed(2)}
                        </td>
                        <td className="py-3 px-3 font-mono text-emerald-400 font-semibold">
                          {currencySymbol}
                          {item.trigger_price.toFixed(2)}
                        </td>
                        <td className="py-3 px-3 font-mono text-purple-300">
                          {item.stage ||
                            (item.rs_rank !== undefined && item.rs_rank !== null
                              ? item.rs_rank.toFixed(1)
                              : "—")}
                        </td>
                        <td className="py-3 px-3 font-mono text-slate-400">
                          {item.pct_from_trigger !== undefined &&
                          item.pct_from_trigger !== null
                            ? `${item.pct_from_trigger > 0 ? "+" : ""}${item.pct_from_trigger.toFixed(1)}%`
                            : "0.0%"}
                        </td>
                        <td className="py-3 px-3 font-mono text-rose-400 font-semibold">
                          {currencySymbol}
                          {item.hard_stop
                            ? item.hard_stop.toFixed(2)
                            : (item.close * 0.92).toFixed(2)}
                        </td>
                        <td className="py-3 px-3 font-mono text-amber-400 font-semibold">
                          {item.trailing_stop
                            ? `${currencySymbol}${item.trailing_stop.toFixed(2)}`
                            : "—"}
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
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-mono text-emerald-400 font-bold">
                {selectedSignal ? selectedSignal.ticker : "None Selected"}
              </span>
              {selectedSignal && (
                <button
                  onClick={() => setChartModalSymbol(selectedSignal.ticker)}
                  className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
                  title="Open Chart"
                >
                  <BarChart2 className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>

          {selectedSignal ? (
            <div className="space-y-4">
              <div className="bg-slate-950 p-2.5 rounded border border-slate-800">
                <span className="text-slate-500 text-[10px] block">
                  Trigger Price
                </span>
                <span className="font-mono text-white font-bold text-sm">
                  {currencySymbol}
                  {selectedSignal.trigger_price.toFixed(2)}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="bg-slate-950/70 p-3 rounded-lg border border-slate-800">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider">
                    Hard Stop
                  </div>
                  <span className="font-mono text-rose-400 font-bold text-sm">
                    {currencySymbol}
                    {selectedSignal.hard_stop !== undefined &&
                    selectedSignal.hard_stop !== null
                      ? selectedSignal.hard_stop.toFixed(2)
                      : (selectedSignal.trigger_price * 0.92).toFixed(2)}
                  </span>
                </div>

                <div className="bg-slate-950/70 p-3 rounded-lg border border-slate-800">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wider">
                    Trailing Stop
                  </div>
                  <span className="font-mono text-amber-400 font-bold text-sm">
                    {selectedSignal.trailing_stop !== undefined &&
                    selectedSignal.trailing_stop !== null
                      ? `${currencySymbol}${selectedSignal.trailing_stop.toFixed(2)}`
                      : "N/A"}
                  </span>
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
                      {currencySymbol}
                      {selectedSignal.suggested_cost?.toLocaleString()}
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

      {/* 75-Minute Chart Viewer Modal */}
      {chartModalSymbol && (
        <Elder75mChartModal
          symbol={chartModalSymbol}
          market={market}
          isOpen={!!chartModalSymbol}
          onClose={() => setChartModalSymbol(null)}
        />
      )}
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
