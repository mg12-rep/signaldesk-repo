"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Briefcase,
  RefreshCw,
  PlayCircle,
  CheckCircle2,
  AlertCircle,
  Upload,
  ArrowLeft,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

interface HoldingItem {
  id: number;
  stock_name: string;
  ticker: string;
  quantity: number;
  avg_buy_price: number;
  current_price: number;
  cost_value: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
  broker: string;
  strategy: string;
  currency: string;
}

interface BrokerStrategySummary {
  broker: string;
  strategy: string;
  currency: string;
  total_pnl: number;
  pnl_pct: number;
  cash_available: number;
  total_cost_value: number;
  total_market_value: number;
  holdings: HoldingItem[];
}

interface ExitRecommendation {
  ticker: string;
  status: "HOLD" | "SELL_FULL" | "SELL_PARTIAL" | "SELL_FULL_OVERDUE" | "ERROR";
  action?: string;
  urgency?: "HIGH" | "MEDIUM" | "LOW";
  reason?: string;
  note?: string;
  current_price?: number;
  current_stop?: number;
  pct_above_stop?: number;
  targets_hit_so_far?: string;
  next_target_price?: number;
  pct_to_next_target?: number;
  shares_to_sell?: number;
  shares_remaining_after?: number;
  trend_template_pass?: boolean;
  rs_rank?: number;
  holding_id?: number;
  broker?: string;
}

type BrokerType = "ZERODHA" | "UPSTOX" | "IBKR";
type StrategyType = "minervini_vcp" | "larry_connors" | "mean_reversion";

export default function HoldingsPage() {
  const [selectedBroker, setSelectedBroker] = useState<BrokerType>("ZERODHA");
  const [selectedStrategy, setSelectedStrategy] =
    useState<StrategyType>("minervini_vcp");
  const [data, setData] = useState<BrokerStrategySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [reconRunning, setReconRunning] = useState(false);
  const [reconMessage, setReconMessage] = useState<string | null>(null);
  const [reconResults, setReconResults] = useState<ExitRecommendation[] | null>(
    null,
  );
  const [activeTab, setActiveTab] = useState<"holdings" | "exit_recon">(
    "holdings",
  );

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    fetchHoldings();
    setReconResults(null);
    setActiveTab("holdings");
  }, [selectedBroker, selectedStrategy]);

  const [syncing, setSyncing] = useState(false);

  // 1. Instant DB Load (No broker call)
  const fetchHoldings = async () => {
    setLoading(true);
    setReconMessage(null);
    try {
      const res = await fetch(
        `http://localhost:8000/api/v1/holdings/data?broker=${selectedBroker}&strategy=${selectedStrategy}`,
      );
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } catch (err) {
      console.error("Failed fetching holdings:", err);
    } finally {
      setLoading(false);
    }
  };

  // 2. Explicit On-Demand Sync (Only when clicking Refresh)
  const handleSyncBroker = async () => {
    setSyncing(true);
    try {
      const res = await fetch(
        `http://localhost:8000/api/v1/holdings/sync/${selectedBroker}?strategy=${selectedStrategy}`,
        { method: "POST" },
      );
      if (res.ok) {
        // After successful broker sync, refresh table from DB
        await fetchHoldings();
      } else {
        const err = await res.json();
        alert(`Sync failed: ${err.detail || "Unable to sync with broker."}`);
      }
    } catch (err) {
      console.error("Broker sync failed:", err);
      alert(
        "Sync request failed. Make sure backend and broker API are running.",
      );
    } finally {
      setSyncing(false);
    }
  };

  const handleFileUpload = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(
        "http://localhost:8000/api/v1/holdings/upload-csv",
        {
          method: "POST",
          body: formData,
        },
      );
      const result = await res.json();
      if (res.ok) {
        alert(`Imported ${result.imported} holdings successfully!`);
        fetchHoldings();
      } else {
        alert(`Error: ${result.detail}`);
      }
    } catch (err) {
      alert("Upload failed. Please check backend server.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleRunExitRecon = async () => {
    setReconRunning(true);
    setReconMessage(null);
    try {
      console.log(
        `Triggering exit recon for ${selectedBroker} - ${selectedStrategy}`,
      );
      const res = await fetch(
        `http://localhost:8000/api/v1/holdings/run-exit-recon?broker=${selectedBroker}&strategy=${selectedStrategy}`,
        { method: "POST" },
      );

      console.log("Response Status:", res.status);
      const json = await res.json();
      console.log("Response JSON:", json);

      if (res.ok) {
        const list: ExitRecommendation[] =
          json.recommendations || json.data || [];
        setReconResults(list);
        setActiveTab("exit_recon");
        setReconMessage(
          `Reconciliation completed (${list.length} positions evaluated)`,
        );
      } else {
        alert(`API Error (${res.status}): ${json.detail || "Unknown error"}`);
      }
    } catch (err: any) {
      console.error("Fetch Error:", err);
      alert(`Network/Fetch Error: ${err.message}`);
      setReconMessage("Failed to execute Exit Recon.");
    } finally {
      setReconRunning(false);
    }
  };

  const currencySymbol = data?.currency === "USD" ? "$" : "₹";

  return (
    <div className="space-y-5 p-1">
      {/* Top Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Briefcase className="h-6 w-6 text-emerald-400" />
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Holdings
          </h1>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept=".csv"
            className="hidden"
          />

          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 px-3 py-1.5 rounded-md text-xs font-medium transition disabled:opacity-50"
          >
            <Upload
              className={`h-3.5 w-3.5 text-blue-400 ${uploading ? "animate-spin" : ""}`}
            />
            <span>{uploading ? "Uploading..." : "Upload CSV"}</span>
          </button>

          <button
            onClick={handleSyncBroker}
            disabled={syncing || loading}
            className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 px-3 py-1.5 rounded-md text-xs font-medium transition disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 text-emerald-400 ${syncing ? "animate-spin" : ""}`}
            />
            <span>{syncing ? "Syncing..." : "Refresh"}</span>
          </button>
        </div>
      </div>

      {/* Broker Selection Tabs */}
      <div className="flex gap-2 border-b border-slate-800 pb-2">
        {(["ZERODHA", "UPSTOX", "IBKR"] as BrokerType[]).map((broker) => {
          const isActive = selectedBroker === broker;
          return (
            <button
              key={broker}
              onClick={() => setSelectedBroker(broker)}
              className={`px-5 py-2 rounded-lg text-xs font-bold tracking-wider transition ${
                isActive
                  ? "bg-amber-600 text-white shadow-lg shadow-amber-950/40"
                  : "bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200"
              }`}
            >
              {broker}
            </button>
          );
        })}
      </div>

      {/* Strategy Tabs */}
      <div className="flex gap-2">
        {[
          { id: "minervini_vcp", label: "Minervini VCP" },
          { id: "larry_connors", label: "Larry Connors" },
          { id: "mean_reversion", label: "Mean Reversion" },
        ].map((strat) => {
          const isActive = selectedStrategy === strat.id;
          return (
            <button
              key={strat.id}
              onClick={() => setSelectedStrategy(strat.id as StrategyType)}
              className={`px-4 py-1.5 rounded-md text-xs font-semibold transition ${
                isActive
                  ? "bg-slate-800 text-emerald-400 border border-emerald-500/50"
                  : "bg-slate-950 border border-slate-800/80 text-slate-400 hover:text-slate-200"
              }`}
            >
              {strat.label}
            </button>
          );
        })}
      </div>

      {/* Summary Card & Exit Recon Button */}
      <div className="bg-slate-900 border border-slate-800/80 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4 shadow-xl">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
          <div>
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Total P/L
            </div>
            <div className="flex items-baseline gap-2 mt-0.5">
              <span
                className={`text-base font-bold font-mono ${(data?.total_pnl || 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}
              >
                {(data?.total_pnl || 0) >= 0 ? "+" : ""}
                {currencySymbol}
                {data?.total_pnl.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                }) || "0.00"}
              </span>
              <span
                className={`text-xs font-bold font-mono ${(data?.pnl_pct || 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}
              >
                ({(data?.pnl_pct || 0) >= 0 ? "+" : ""}
                {data?.pnl_pct || "0.00"}%)
              </span>
            </div>
          </div>

          <div className="h-8 w-[1px] bg-slate-800 hidden sm:block" />

          <div>
            <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Cash Available
            </div>
            <div className="text-base font-bold font-mono text-white mt-0.5">
              {currencySymbol}
              {data?.cash_available.toLocaleString(undefined, {
                minimumFractionDigits: 2,
              }) || "0.00"}
            </div>
          </div>
        </div>

        {/* View Switch / Run Exit Recon */}
        <div className="flex items-center gap-3">
          {reconResults && (
            <div className="flex bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs">
              <button
                onClick={() => setActiveTab("holdings")}
                className={`px-3 py-1.5 rounded-md font-semibold transition ${
                  activeTab === "holdings"
                    ? "bg-slate-800 text-white"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                Holdings View
              </button>
              <button
                onClick={() => setActiveTab("exit_recon")}
                className={`px-3 py-1.5 rounded-md font-semibold transition ${
                  activeTab === "exit_recon"
                    ? "bg-purple-900 text-purple-200"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                Exit Recon ({reconResults.length})
              </button>
            </div>
          )}

          <button
            onClick={handleRunExitRecon}
            disabled={reconRunning}
            className="flex items-center gap-2 bg-purple-700 hover:bg-purple-600 text-white font-semibold text-xs px-5 py-2.5 rounded-lg shadow-lg shadow-purple-950/40 transition active:scale-[0.98] disabled:opacity-50"
          >
            <PlayCircle
              className={`h-4 w-4 ${reconRunning ? "animate-spin" : ""}`}
            />
            <span>{reconRunning ? "Running Recon..." : "Run Exit Recon"}</span>
          </button>
        </div>
      </div>

      {/* VIEW 1: Standard Holdings Table */}
      {activeTab === "holdings" && (
        <div className="bg-slate-900 border border-slate-800/80 rounded-xl overflow-hidden shadow-xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-[11px] font-semibold text-slate-400 uppercase tracking-wider bg-slate-950/50">
                  <th className="py-3 px-4">Stock Name</th>
                  <th className="py-3 px-3">Ticker</th>
                  <th className="py-3 px-3 text-right">Quantity</th>
                  <th className="py-3 px-3 text-right">Avg. Buy Price</th>
                  <th className="py-3 px-3 text-right">Current Price</th>
                  <th className="py-3 px-3 text-right">Cost Value</th>
                  <th className="py-3 px-3 text-right">Market Value</th>
                  <th className="py-3 px-3 text-right">P/L</th>
                  <th className="py-3 px-4 text-right">P/L %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-xs font-mono">
                {loading ? (
                  <tr>
                    <td
                      colSpan={9}
                      className="py-12 text-center text-slate-500"
                    >
                      Loading holdings data for {selectedBroker} (
                      {selectedStrategy})...
                    </td>
                  </tr>
                ) : data?.holdings.length === 0 ? (
                  <tr>
                    <td
                      colSpan={9}
                      className="py-12 text-center text-slate-500"
                    >
                      No active positions found for {selectedBroker} under{" "}
                      {selectedStrategy}.
                    </td>
                  </tr>
                ) : (
                  data?.holdings.map((h) => {
                    const isPositive = h.pnl >= 0;
                    return (
                      <tr
                        key={h.id}
                        className="hover:bg-slate-800/40 transition"
                      >
                        <td className="py-3 px-4 font-sans font-medium text-slate-200">
                          {h.stock_name}
                        </td>
                        <td className="py-3 px-3 font-bold text-white">
                          {h.ticker}
                        </td>
                        <td className="py-3 px-3 text-right text-slate-300">
                          {h.quantity}
                        </td>
                        <td className="py-3 px-3 text-right text-slate-300">
                          {currencySymbol}
                          {h.avg_buy_price.toFixed(2)}
                        </td>
                        <td className="py-3 px-3 text-right font-bold text-white">
                          {currencySymbol}
                          {h.current_price.toFixed(2)}
                        </td>
                        <td className="py-3 px-3 text-right text-slate-300">
                          {currencySymbol}
                          {h.cost_value.toLocaleString(undefined, {
                            minimumFractionDigits: 2,
                          })}
                        </td>
                        <td className="py-3 px-3 text-right font-bold text-slate-100">
                          {currencySymbol}
                          {h.market_value.toLocaleString(undefined, {
                            minimumFractionDigits: 2,
                          })}
                        </td>
                        <td
                          className={`py-3 px-3 text-right font-bold ${isPositive ? "text-emerald-400" : "text-rose-400"}`}
                        >
                          {isPositive ? "+" : ""}
                          {currencySymbol}
                          {h.pnl.toLocaleString(undefined, {
                            minimumFractionDigits: 2,
                          })}
                        </td>
                        <td
                          className={`py-3 px-4 text-right font-bold ${isPositive ? "text-emerald-400" : "text-rose-400"}`}
                        >
                          {isPositive ? "+" : ""}
                          {h.pnl_pct.toFixed(2)}%
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* VIEW 2: Exit Reconciliation Recommendations Table */}
      {activeTab === "exit_recon" && reconResults && (
        <div className="bg-slate-900 border border-slate-800/80 rounded-xl overflow-hidden shadow-xl">
          <div className="p-4 bg-slate-950/70 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-purple-400" />
              <h2 className="text-sm font-bold text-white uppercase tracking-wider">
                Minervini VCP Exit Recommendations
              </h2>
            </div>
            <span className="text-xs text-slate-400 font-mono">
              Evaluated: {reconResults.length} positions
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-[11px] font-semibold text-slate-400 uppercase tracking-wider bg-slate-950/40">
                  <th className="py-3 px-4">Action</th>
                  <th className="py-3 px-3">Ticker</th>
                  <th className="py-3 px-3 text-right">LTP</th>
                  <th className="py-3 px-3 text-right">Current Stop</th>
                  <th className="py-3 px-3 text-right">% Above Stop</th>
                  <th className="py-3 px-3">Targets Hit</th>
                  <th className="py-3 px-3 text-right">Next Target</th>
                  <th className="py-3 px-3 text-center">RS Rank</th>
                  <th className="py-3 px-4">Notes / Trigger</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-xs font-mono">
                {reconResults.map((r, idx) => {
                  let badge = (
                    <span className="px-2.5 py-1 rounded font-bold text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800">
                      HOLD
                    </span>
                  );
                  if (r.status === "SELL_FULL_OVERDUE") {
                    badge = (
                      <span className="px-2.5 py-1 rounded font-bold text-[10px] bg-rose-950 text-rose-300 border border-rose-700 animate-pulse">
                        SELL (OVERDUE)
                      </span>
                    );
                  } else if (r.status === "SELL_FULL") {
                    badge = (
                      <span className="px-2.5 py-1 rounded font-bold text-[10px] bg-rose-900 text-rose-200 border border-rose-600">
                        SELL FULL
                      </span>
                    );
                  } else if (r.status === "SELL_PARTIAL") {
                    badge = (
                      <span className="px-2.5 py-1 rounded font-bold text-[10px] bg-amber-950 text-amber-300 border border-amber-700">
                        TRIM +{r.shares_to_sell}
                      </span>
                    );
                  } else if (r.status === "ERROR") {
                    badge = (
                      <span className="px-2.5 py-1 rounded font-bold text-[10px] bg-slate-800 text-slate-400 border border-slate-700">
                        NO DATA
                      </span>
                    );
                  }

                  return (
                    <tr key={idx} className="hover:bg-slate-800/40 transition">
                      <td className="py-3 px-4">{badge}</td>
                      <td className="py-3 px-3 font-bold text-white">
                        {r.ticker}
                      </td>
                      <td className="py-3 px-3 text-right font-bold text-slate-100">
                        {r.current_price
                          ? `${currencySymbol}${r.current_price.toFixed(2)}`
                          : "-"}
                      </td>
                      <td className="py-3 px-3 text-right text-amber-400 font-medium">
                        {r.current_stop
                          ? `${currencySymbol}${r.current_stop.toFixed(2)}`
                          : "-"}
                      </td>
                      <td className="py-3 px-3 text-right text-emerald-400">
                        {r.pct_above_stop !== undefined &&
                        r.pct_above_stop !== null
                          ? `+${r.pct_above_stop.toFixed(2)}%`
                          : "-"}
                      </td>
                      <td className="py-3 px-3 text-slate-300">
                        {r.targets_hit_so_far || "-"}
                      </td>
                      <td className="py-3 px-3 text-right text-slate-300">
                        {r.next_target_price
                          ? `${currencySymbol}${r.next_target_price.toFixed(2)}`
                          : "-"}
                      </td>
                      <td className="py-3 px-3 text-center font-bold text-blue-400">
                        {r.rs_rank !== undefined && r.rs_rank !== null
                          ? r.rs_rank.toFixed(1)
                          : "-"}
                      </td>
                      <td className="py-3 px-4 font-sans text-xs text-slate-400">
                        {r.reason ||
                          r.note ||
                          "Position healthy within standard trail parameters."}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
