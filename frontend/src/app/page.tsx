"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  TrendingUp,
  Activity,
  RefreshCw,
  Database,
  Wallet,
  AlertTriangle,
  Layers,
  Clock,
} from "lucide-react";

interface AccountBalance {
  account_name: string;
  broker: string;
  currency: string;
  portfolio_value: number;
  cash_available: number;
  buying_power: number;
}

interface MarketHealthItem {
  index_name: string;
  symbol: string;
  close: number;
  change_pct: number;
  sma_50: number;
  sma_200: number;
  status: "HEALTHY" | "CAUTION" | "UNHEALTHY";
}

interface DashboardSummary {
  total_open_risk_pct: number;
  max_portfolio_heat_pct: number;
  open_positions_count: number;
  max_position_slots: number;
  candidates_count: number;
  accounts: AccountBalance[];
  market_health: MarketHealthItem[];
}

type SyncTarget = "NSE_DAILY" | "US_DAILY" | "US_ETFS" | "NSE_15M" | "US_15M";

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncingTarget, setSyncingTarget] = useState<SyncTarget | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const fetchDashboardData = async () => {
    setLoading(true);
    try {
      const res = await fetch("http://localhost:8000/api/v1/dashboard/summary");
      if (res.ok) {
        const data = await res.json();
        setSummary(data);
      }
    } catch (err) {
      console.error("Dashboard summary fetch failed:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const triggerSync = async (target: SyncTarget) => {
    setSyncingTarget(target);
    setStatusMsg(null);

    let endpoint = "";
    if (target === "NSE_DAILY")
      endpoint = "http://localhost:8000/api/v1/sync/nse/daily?full_seed=false";
    if (target === "US_DAILY")
      endpoint = "http://localhost:8000/api/v1/sync/us/daily";
    if (target === "US_ETFS")
      endpoint = "http://localhost:8000/api/v1/sync/us-etfs";
    if (target === "NSE_15M") {
      endpoint =
        "http://localhost:8000/api/v1/sync/nse/15min?csv_path=C:/work/signaldesk/data/elder_input_nse_stocks.csv&days=90";
    }
    if (target === "US_15M") {
      endpoint =
        "http://localhost:8000/api/v1/sync/us/15min?csv_path=C:/work/signaldesk/data/elder_input_us_stocks.csv&days=90";
    }

    try {
      const res = await fetch(endpoint, { method: "POST" });
      if (res.ok) {
        const json = await res.json();
        setStatusMsg(json.message || `${target} sync initiated in background.`);
      } else {
        setStatusMsg(`Failed to trigger ${target}. Check backend console.`);
      }
    } catch (e) {
      console.error("Sync failed", e);
      setStatusMsg(`Network error triggering ${target}.`);
    } finally {
      setTimeout(() => setSyncingTarget(null), 2000);
      setTimeout(() => setStatusMsg(null), 6000);
    }
  };

  const getCurrencySymbol = (curr: string) => {
    if (curr === "INR") return "₹";
    if (curr === "USD") return "$";
    if (curr === "CAD") return "C$";
    return "";
  };

  return (
    <div className="space-y-8 p-1">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Executive Dashboard
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Multi-broker account telemetry, risk budget, and market health
            regimes
          </p>
        </div>

        {/* Sync Controls Toolbar */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Daily Sync Group */}
          <div className="flex items-center bg-slate-950 p-1 rounded-lg border border-slate-800 gap-1">
            <button
              onClick={() => triggerSync("NSE_DAILY")}
              disabled={syncingTarget !== null}
              className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 px-2.5 py-1 rounded text-xs font-medium transition disabled:opacity-50"
            >
              <Database
                className={`h-3.5 w-3.5 text-blue-400 ${syncingTarget === "NSE_DAILY" ? "animate-spin" : ""}`}
              />
              <span>
                {syncingTarget === "NSE_DAILY" ? "Syncing..." : "NSE Daily"}
              </span>
            </button>

            <button
              onClick={() => triggerSync("US_DAILY")}
              disabled={syncingTarget !== null}
              className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 px-2.5 py-1 rounded text-xs font-medium transition disabled:opacity-50"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 text-emerald-400 ${syncingTarget === "US_DAILY" ? "animate-spin" : ""}`}
              />
              <span>
                {syncingTarget === "US_DAILY" ? "Syncing..." : "US Daily"}
              </span>
            </button>

            <button
              onClick={() => triggerSync("US_ETFS")}
              disabled={syncingTarget !== null}
              className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 px-2.5 py-1 rounded text-xs font-medium transition disabled:opacity-50"
            >
              <Layers
                className={`h-3.5 w-3.5 text-purple-400 ${syncingTarget === "US_ETFS" ? "animate-spin" : ""}`}
              />
              <span>{syncingTarget === "US_ETFS" ? "Syncing..." : "ETFs"}</span>
            </button>
          </div>

          {/* Intraday 15m Elder Sync Group */}
          <div className="flex items-center bg-slate-950 p-1 rounded-lg border border-cyan-900/50 gap-1">
            <button
              onClick={() => triggerSync("NSE_15M")}
              disabled={syncingTarget !== null}
              title="Syncs 15m bars from elder_input_nse_stocks.csv"
              className="flex items-center gap-1.5 bg-cyan-950/40 hover:bg-cyan-900/60 text-cyan-300 border border-cyan-800/60 px-2.5 py-1 rounded text-xs font-medium transition disabled:opacity-50"
            >
              <Clock
                className={`h-3.5 w-3.5 text-cyan-400 ${syncingTarget === "NSE_15M" ? "animate-spin" : ""}`}
              />
              <span>
                {syncingTarget === "NSE_15M" ? "Syncing..." : "NSE 15m"}
              </span>
            </button>

            <button
              onClick={() => triggerSync("US_15M")}
              disabled={syncingTarget !== null}
              title="Syncs 15m bars from elder_input_us_stocks.csv via IBKR"
              className="flex items-center gap-1.5 bg-cyan-950/40 hover:bg-cyan-900/60 text-cyan-300 border border-cyan-800/60 px-2.5 py-1 rounded text-xs font-medium transition disabled:opacity-50"
            >
              <Clock
                className={`h-3.5 w-3.5 text-cyan-400 ${syncingTarget === "US_15M" ? "animate-spin" : ""}`}
              />
              <span>
                {syncingTarget === "US_15M" ? "Syncing..." : "US 15m"}
              </span>
            </button>
          </div>
        </div>
      </div>

      {/* Notification Banner */}
      {statusMsg && (
        <div className="p-3 bg-blue-950/40 border border-blue-800/60 rounded-lg text-xs text-blue-300 font-mono flex items-center justify-between">
          <span>{statusMsg}</span>
          <button
            onClick={() => setStatusMsg(null)}
            className="text-slate-500 hover:text-white"
          >
            ✕
          </button>
        </div>
      )}

      {/* Top Operational Telemetry */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Risk Budget Card */}
        <div className="bg-slate-900 border border-slate-800/80 p-4 rounded-xl">
          <div className="flex justify-between items-center text-slate-400 text-xs mb-2">
            <span>Portfolio Risk Heat</span>
            <AlertTriangle className="h-4 w-4 text-amber-400" />
          </div>
          <div className="text-xl font-bold font-mono text-white">
            {summary?.total_open_risk_pct}%{" "}
            <span className="text-xs text-slate-500 font-normal">
              / {summary?.max_portfolio_heat_pct}% Max
            </span>
          </div>
          <div className="text-[11px] text-emerald-400 mt-1">
            Risk budget within safe limits
          </div>
        </div>

        {/* Position Slots Card */}
        <div className="bg-slate-900 border border-slate-800/80 p-4 rounded-xl">
          <div className="flex justify-between items-center text-slate-400 text-xs mb-2">
            <span>Position Slots</span>
            <Activity className="h-4 w-4 text-blue-400" />
          </div>
          <div className="text-xl font-bold font-mono text-white">
            {summary?.open_positions_count}{" "}
            <span className="text-xs text-slate-500 font-normal">
              / {summary?.max_position_slots} Max
            </span>
          </div>
          <Link
            href="/holdings"
            className="text-[11px] text-blue-400 hover:underline mt-1 block"
          >
            Manage stop-loss & exits →
          </Link>
        </div>

        {/* Strategy Candidates Card */}
        <div className="bg-slate-900 border border-slate-800/80 p-4 rounded-xl">
          <div className="flex justify-between items-center text-slate-400 text-xs mb-2">
            <span>Strategy Candidates</span>
            <TrendingUp className="h-4 w-4 text-purple-400" />
          </div>
          <div className="text-xl font-bold font-mono text-white">
            {summary?.candidates_count}{" "}
            <span className="text-xs text-slate-400 font-normal">
              Actionable
            </span>
          </div>
          <Link
            href="/scanners"
            className="text-[11px] text-purple-400 hover:underline mt-1 block"
          >
            Review order tickets →
          </Link>
        </div>
      </div>

      {/* Account Balances by Native Currency */}
      <div className="bg-slate-900 border border-slate-800/80 rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Wallet className="h-4 w-4 text-emerald-400" />
            <h2 className="text-sm font-bold text-white">
              Broker Accounts & Capital
            </h2>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {summary?.accounts.map((acc) => {
            const sym = getCurrencySymbol(acc.currency);
            return (
              <div
                key={acc.account_name}
                className="bg-slate-950/60 border border-slate-800/90 rounded-lg p-4 space-y-3"
              >
                <div className="flex justify-between items-center">
                  <div>
                    <div className="font-semibold text-white text-xs">
                      {acc.account_name}
                    </div>
                    <div className="text-[10px] text-slate-400 font-mono">
                      {acc.broker} • {acc.currency}
                    </div>
                  </div>
                  <span className="bg-slate-800 text-slate-300 text-[10px] px-2 py-0.5 rounded font-mono font-medium">
                    {acc.currency}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-800/60">
                  <div>
                    <div className="text-[10px] text-slate-400">
                      Portfolio Value
                    </div>
                    <div className="font-mono text-sm font-bold text-white">
                      {sym}
                      {acc.portfolio_value.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                      })}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-400">
                      Available Cash
                    </div>
                    <div className="font-mono text-sm font-bold text-emerald-400">
                      {sym}
                      {acc.cash_available.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                      })}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Market Health & Regime Status */}
      <div className="bg-slate-900 border border-slate-800/80 rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div>
            <h2 className="text-sm font-bold text-white">
              Market Regime & Health Monitor
            </h2>
            <p className="text-[11px] text-slate-400">
              Trend template regime checks (SMA 50 &gt; SMA 200) controlling new
              buy authorizations
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {summary?.market_health.map((idx) => (
            <div
              key={idx.symbol}
              className="bg-slate-950/60 border border-slate-800/90 rounded-lg p-3.5 space-y-2"
            >
              <div className="flex justify-between items-start">
                <div>
                  <div className="font-semibold text-white text-xs">
                    {idx.index_name}
                  </div>
                  <div className="text-[10px] text-slate-400 font-mono">
                    {idx.symbol}
                  </div>
                </div>
                <span className="bg-emerald-950 text-emerald-400 border border-emerald-800 text-[10px] px-2 py-0.5 rounded font-bold">
                  {idx.status}
                </span>
              </div>

              <div className="flex justify-between items-baseline pt-1">
                <span className="font-mono text-sm font-bold text-white">
                  {idx.close.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                  })}
                </span>
                <span
                  className={`text-xs font-mono font-medium flex items-center ${idx.change_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}
                >
                  {idx.change_pct >= 0 ? "+" : ""}
                  {idx.change_pct}%
                </span>
              </div>

              <div className="text-[10px] text-slate-400 flex justify-between pt-1 border-t border-slate-800/60 font-mono">
                <span>SMA50: {idx.sma_50}</span>
                <span>SMA200: {idx.sma_200}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
