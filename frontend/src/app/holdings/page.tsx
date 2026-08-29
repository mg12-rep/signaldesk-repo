"use client";

import React, { useState, useEffect } from "react";
import { Upload, FileSpreadsheet } from "lucide-react";
import { useRef } from "react";
import {
  Briefcase,
  RefreshCw,
  PlayCircle,
  CheckCircle2,
  AlertCircle,
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

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
        fetchHoldings(); // Refresh current table
      } else {
        alert(`Error: ${result.detail}`);
      }
    } catch (err) {
      alert("Upload failed. Please check the backend server.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

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

  useEffect(() => {
    fetchHoldings();
  }, [selectedBroker, selectedStrategy]);

  const handleRunExitRecon = async () => {
    setReconRunning(true);
    setReconMessage(null);
    try {
      const res = await fetch(
        `http://localhost:8000/api/v1/holdings/run-exit-recon?broker=${selectedBroker}&strategy=${selectedStrategy}`,
        { method: "POST" },
      );
      if (res.ok) {
        const json = await res.json();
        setReconMessage(json.message);
      }
    } catch (err) {
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

        {/* Top Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Briefcase className="h-6 w-6 text-emerald-400" />
            <h1 className="text-2xl font-bold text-white tracking-tight">
              Holdings
            </h1>
          </div>

          {/* Top Action Buttons Group */}
          <div className="flex items-center gap-2">
            {/* Hidden File Input */}
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileUpload}
              accept=".csv"
              className="hidden"
            />

            {/* Upload CSV Trigger Button */}
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

            {/* Refresh Button */}
            <button
              onClick={fetchHoldings}
              disabled={loading}
              className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 px-3 py-1.5 rounded-md text-xs font-medium transition"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 text-emerald-400 ${loading ? "animate-spin" : ""}`}
              />
              <span>Refresh</span>
            </button>
          </div>
        </div>
      </div>

      {/* Tier 1: Broker Selection Tabs */}
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

      {/* Tier 2: Strategy Sub-Tabs */}
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

      {/* Account Metric & Exit Recon Action Strip */}
      <div className="bg-slate-900 border border-slate-800/80 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4 shadow-xl">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
          {/* Total P/L & % */}
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

          {/* Cash Available */}
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

        {/* Exit Recon Button */}
        <div className="flex items-center gap-3">
          {reconMessage && (
            <span className="text-xs font-mono text-emerald-400 flex items-center gap-1">
              <CheckCircle2 className="h-3.5 w-3.5" /> {reconMessage}
            </span>
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

      {/* Main Holdings Table */}
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
                  <td colSpan={9} className="py-12 text-center text-slate-500">
                    Loading holdings data for {selectedBroker} (
                    {selectedStrategy})...
                  </td>
                </tr>
              ) : data?.holdings.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-slate-500">
                    No active positions found for {selectedBroker} under{" "}
                    {selectedStrategy}.
                  </td>
                </tr>
              ) : (
                data?.holdings.map((h) => {
                  const isPositive = h.pnl >= 0;
                  return (
                    <tr key={h.id} className="hover:bg-slate-800/40 transition">
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
    </div>
  );
}
