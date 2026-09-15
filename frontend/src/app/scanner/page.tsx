"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { Sliders, Layers, FileSpreadsheet, Play, Zap } from "lucide-react";

type ScanMode = "UNIVERSE" | "CUSTOM_FILE";
type PredefinedUniverse =
  | "NSE_500"
  | "NSE_ALL"
  | "SP_500"
  | "NASDAQ_100"
  | "US_ETFS";
type MarketType = "NSE" | "US";

const STRATEGY_FILE_DEFAULTS: Record<string, Record<MarketType, string>> = {
  elder_impulse_75m: {
    NSE: "C:/work/signaldesk/data/elder_input_nse_stocks.csv",
    US: "C:/work/signaldesk/data/elder_input_us_stocks.csv",
  },
  minervini_vcp: {
    NSE: "C:/Work/signaldesk/data/evergreen_filter_stocks.csv",
    US: "C:/Work/signaldesk/data/evergreen_filter_us_stocks.csv",
  },
  high_tight_flag: {
    NSE: "C:/Work/signaldesk/data/htf_candidates_nse.csv",
    US: "C:/Work/signaldesk/data/htf_candidates_us.csv",
  },
  relative_strength_leaders: {
    NSE: "C:/Work/signaldesk/data/rs_leaders_nse.csv",
    US: "C:/Work/signaldesk/data/rs_leaders_us.csv",
  },
};

const resolveDefaultPath = (strategy: string, market: MarketType): string => {
  return (
    STRATEGY_FILE_DEFAULTS[strategy]?.[market] ||
    "C:/Work/signaldesk/data/evergreen_filter_stocks.csv"
  );
};

export default function ScannerConfigPage() {
  const router = useRouter();

  // Configuration States
  const [strategyModel, setStrategyModel] = useState("minervini_vcp");
  const [scanMode, setScanMode] = useState<ScanMode>("UNIVERSE");
  const [selectedUniverse, setSelectedUniverse] =
    useState<PredefinedUniverse>("NSE_500");
  const [customFileMarket, setCustomFileMarket] = useState<MarketType>("NSE");
  const [customFilePath, setCustomFilePath] = useState(
    resolveDefaultPath("minervini_vcp", "NSE"),
  );
  const [isRunning, setIsRunning] = useState(false);

  // Dynamic strategy change handler
  const handleStrategyChange = (newStrategy: string) => {
    setStrategyModel(newStrategy);

    if (newStrategy === "weinstein_etf") {
      setScanMode("UNIVERSE");
      setSelectedUniverse("US_ETFS");
    } else if (newStrategy === "elder_impulse_75m") {
      setScanMode("CUSTOM_FILE");
      setCustomFilePath(resolveDefaultPath(newStrategy, customFileMarket));
    } else {
      // Revert to strategy's specific default path for the current active market
      setCustomFilePath(resolveDefaultPath(newStrategy, customFileMarket));
    }
  };

  // Dynamic market change handler
  const handleMarketChange = (m: MarketType) => {
    setCustomFileMarket(m);
    setCustomFilePath(resolveDefaultPath(strategyModel, m));
  };

  const handleLaunchScan = () => {
    setIsRunning(true);

    const queryParams = new URLSearchParams({
      strategy: strategyModel,
      mode: scanMode,
      ...(scanMode === "UNIVERSE"
        ? { universe: selectedUniverse }
        : { custom_path: customFilePath, market: customFileMarket }),
    });

    router.push(`/results?${queryParams.toString()}`);
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8 p-1">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2.5">
          <Sliders className="h-6 w-6 text-emerald-400" />
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Strategy Scanner
          </h1>
        </div>
        <p className="text-xs text-slate-400 mt-1">
          Select parameters and launch real-time scans against the database.
        </p>
      </div>

      {/* Main Configuration Card */}
      <div className="bg-slate-900 border border-slate-800/80 rounded-xl p-6 space-y-7 shadow-xl">
        {/* Strategy Model Dropdown */}
        <div className="space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-300">
            Strategy Model
          </label>
          <select
            value={strategyModel}
            onChange={(e) => handleStrategyChange(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-emerald-500 transition"
          >
            <option value="minervini_vcp">
              Minervini Stage-2 VCP Breakout
            </option>
            <option value="elder_impulse_75m">
              Alexander Elder 75-Min Impulse System (Intraday)
            </option>
            <option value="weinstein_etf">
              Stan Weinstein US ETF Stage Screener
            </option>
            <option value="high_tight_flag">High Tight Flag (HTF)</option>
            <option value="relative_strength_leaders">
              Relative Strength RS-90 Leaders
            </option>
          </select>
        </div>

        {/* Strategy Details Banner for Elder Impulse */}
        {strategyModel === "elder_impulse_75m" && (
          <div className="p-3 bg-cyan-950/30 border border-cyan-800/50 rounded-lg text-xs text-cyan-300 flex items-start gap-2">
            <Zap className="h-4 w-4 text-cyan-400 mt-0.5 shrink-0" />
            <div>
              <span className="font-semibold">
                75-Minute Multi-Timeframe Impulse:
              </span>{" "}
              Scans the 5 daily intraday bars against daily EMA trend stacks,
              volume expansion (&ge;1.25x), and recent timing sequences
              (Green/Blue/Red transitions)[cite: 2].
            </div>
          </div>
        )}

        <div className="border-t border-slate-800/70" />

        {/* Option 1: Target Universe Selection */}
        <div
          className={`space-y-3 transition-opacity ${scanMode !== "UNIVERSE" ? "opacity-40" : "opacity-100"}`}
        >
          <div
            onClick={() => setScanMode("UNIVERSE")}
            className="flex items-center gap-2 cursor-pointer select-none"
          >
            <div
              className={`h-4 w-4 rounded-full border flex items-center justify-center ${scanMode === "UNIVERSE" ? "border-emerald-400 bg-emerald-950/60" : "border-slate-600"}`}
            >
              {scanMode === "UNIVERSE" && (
                <div className="h-2 w-2 rounded-full bg-emerald-400" />
              )}
            </div>
            <Layers className="h-4 w-4 text-emerald-400" />
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-200">
              Option 1: Predefined Universe
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 pt-1">
            {[
              { id: "NSE_500", label: "NSE 500" },
              { id: "NSE_ALL", label: "NSE (All Stocks)" },
              { id: "SP_500", label: "S&P 500" },
              { id: "NASDAQ_100", label: "NASDAQ 100" },
              { id: "US_ETFS", label: "US ETFs" },
            ].map((u) => {
              const isSelected =
                scanMode === "UNIVERSE" && selectedUniverse === u.id;
              return (
                <button
                  key={u.id}
                  type="button"
                  disabled={scanMode !== "UNIVERSE"}
                  onClick={() =>
                    setSelectedUniverse(u.id as PredefinedUniverse)
                  }
                  className={`py-2.5 px-3 rounded-lg text-xs font-medium border transition text-center ${
                    isSelected
                      ? "bg-emerald-950/50 border-emerald-500/80 text-emerald-300 shadow-sm"
                      : "bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200 disabled:cursor-not-allowed"
                  }`}
                >
                  {u.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="border-t border-slate-800/70" />

        {/* Option 2: Custom Shortlist / Filter CSV */}
        <div
          className={`space-y-4 transition-opacity ${scanMode !== "CUSTOM_FILE" ? "opacity-40" : "opacity-100"}`}
        >
          <div
            onClick={() => setScanMode("CUSTOM_FILE")}
            className="flex items-center gap-2 cursor-pointer select-none"
          >
            <div
              className={`h-4 w-4 rounded-full border flex items-center justify-center ${scanMode === "CUSTOM_FILE" ? "border-emerald-400 bg-emerald-950/60" : "border-slate-600"}`}
            >
              {scanMode === "CUSTOM_FILE" && (
                <div className="h-2 w-2 rounded-full bg-emerald-400" />
              )}
            </div>
            <FileSpreadsheet className="h-4 w-4 text-emerald-400" />
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-200">
              Option 2: Custom Shortlist / Filter File
            </span>
          </div>

          <div className="space-y-3 pt-1">
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-400">
                File Market Universe:
              </span>
              <div className="flex gap-2">
                {(["NSE", "US"] as MarketType[]).map((m) => {
                  const isMarketSelected =
                    scanMode === "CUSTOM_FILE" && customFileMarket === m;
                  return (
                    <button
                      key={m}
                      type="button"
                      disabled={scanMode !== "CUSTOM_FILE"}
                      onClick={() => handleMarketChange(m)}
                      className={`px-3 py-1 text-xs rounded border transition font-mono ${
                        isMarketSelected
                          ? "bg-emerald-950/60 border-emerald-500 text-emerald-300 font-semibold"
                          : "bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200 disabled:cursor-not-allowed"
                      }`}
                    >
                      {m}
                    </button>
                  );
                })}
              </div>
            </div>

            <input
              type="text"
              disabled={scanMode !== "CUSTOM_FILE"}
              value={customFilePath}
              onChange={(e) => setCustomFilePath(e.target.value)}
              placeholder="e.g. C:/Work/signaldesk/data/my_screen.csv"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-emerald-500 disabled:cursor-not-allowed transition"
            />
          </div>
        </div>

        {/* Action Button */}
        <div className="flex justify-end pt-4 border-t border-slate-800">
          <button
            onClick={handleLaunchScan}
            disabled={isRunning}
            className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs px-5 py-2.5 rounded-lg shadow-lg shadow-emerald-950/40 transition active:scale-[0.98] disabled:opacity-50"
          >
            <Play
              className={`h-4 w-4 fill-current ${isRunning ? "animate-pulse" : ""}`}
            />
            <span>{isRunning ? "Launching Scanner..." : "Run Scanner"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
