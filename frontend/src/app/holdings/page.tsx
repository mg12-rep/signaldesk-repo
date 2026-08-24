"use client";

import React, { useState } from "react";
import { AlertCircle, Filter } from "lucide-react";

export default function HoldingsScreen() {
  const [activeStrategy, setActiveStrategy] = useState<
    "ALL" | "MINERVINI" | "CONNORS"
  >("MINERVINI");
  const [activeBroker, setActiveBroker] = useState<
    "ALL" | "ZERODHA" | "UPSTOX" | "IBKR"
  >("ALL");

  // Mock Position Records with Strategy and Broker mappings
  const holdingsData = [
    {
      id: 1,
      name: "Tata Motors",
      ticker: "TATAMOTORS",
      broker: "ZERODHA",
      strategy: "MINERVINI",
      qty: 25,
      entryPrice: 920.0,
      currentPrice: 1040.0,
      pnlPct: 13.0,
      pnlAmt: 3000.0,
      highestClose: 1060.0,
      activeStop: 975.2,
      action: "HOLD",
      reason: "Above 50 SMA & Trailing Stop",
    },
    {
      id: 2,
      name: "Bharat Electronics",
      ticker: "BEL",
      broker: "ZERODHA",
      strategy: "MINERVINI",
      qty: 80,
      entryPrice: 285.0,
      currentPrice: 310.0,
      pnlPct: 8.7,
      pnlAmt: 2000.0,
      highestClose: 310.0,
      activeStop: 285.2,
      action: "HOLD",
      reason: "Above 50 SMA & Trailing Stop",
    },
    {
      id: 3,
      name: "Coforge Ltd",
      ticker: "COFORGE",
      broker: "UPSTOX",
      strategy: "MINERVINI",
      qty: 12,
      entryPrice: 7100.0,
      currentPrice: 6720.0,
      pnlPct: -5.3,
      pnlAmt: -4560.0,
      highestClose: 7250.0,
      activeStop: 6670.0,
      action: "SELL",
      reason: "Close < 50 SMA Breakdown",
    },
    {
      id: 4,
      name: "State Bank of India",
      ticker: "SBIN",
      broker: "ZERODHA",
      strategy: "CONNORS",
      qty: 60,
      entryPrice: 810.0,
      currentPrice: 838.0,
      pnlPct: 3.4,
      pnlAmt: 1680.0,
      daysHeld: 3,
      currentRSI2: 74.2,
      sma5: 825.0,
      action: "SELL",
      reason: "RSI(2) > 70 & Close > 5-Day SMA",
    },
    {
      id: 5,
      name: "ICICI Bank",
      ticker: "ICICIBANK",
      broker: "UPSTOX",
      strategy: "CONNORS",
      qty: 40,
      entryPrice: 1240.0,
      currentPrice: 1255.0,
      pnlPct: 1.2,
      pnlAmt: 600.0,
      daysHeld: 2,
      currentRSI2: 45.0,
      sma5: 1262.0,
      action: "HOLD",
      reason: "Pullback bounce in progress",
    },
    {
      id: 6,
      name: "Vanguard FTSE All-World",
      ticker: "VWRA",
      broker: "IBKR",
      strategy: "MINERVINI",
      qty: 50,
      entryPrice: 125.0,
      currentPrice: 132.5,
      pnlPct: 6.0,
      pnlAmt: 375.0,
      highestClose: 134.0,
      activeStop: 124.0,
      action: "HOLD",
      reason: "Above 50 SMA",
    },
  ];

  // Combined Strategy & Broker Filter
  const filteredHoldings = holdingsData.filter((h) => {
    const matchStrategy =
      activeStrategy === "ALL" ? true : h.strategy === activeStrategy;
    const matchBroker =
      activeBroker === "ALL" ? true : h.broker === activeBroker;
    return matchStrategy && matchBroker;
  });

  const totalUnrealized = filteredHoldings.reduce(
    (sum, h) => sum + h.pnlAmt,
    0,
  );

  // Broker badge visual styling
  const getBrokerBadge = (broker: string) => {
    switch (broker) {
      case "ZERODHA":
        return "bg-emerald-950/80 text-emerald-300 border-emerald-800/80";
      case "UPSTOX":
        return "bg-violet-950/80 text-violet-300 border-violet-800/80";
      case "IBKR":
        return "bg-amber-950/80 text-amber-300 border-amber-800/80";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-xl font-bold text-white">
            Holdings & Exit Monitor
          </h1>
          <p className="text-slate-400 text-xs mt-0.5">
            Multi-broker portfolio tracking with strategy-specific daily exit
            rules
          </p>
        </div>

        {/* Total PnL Pill */}
        <div className="bg-slate-900 border border-slate-800 px-4 py-2 rounded-lg text-right flex items-center gap-4">
          <div>
            <div className="text-[10px] text-slate-500 font-semibold uppercase">
              Total Unrealized P&L
            </div>
            <div
              className={`text-base font-bold font-mono ${totalUnrealized >= 0 ? "text-emerald-400" : "text-rose-400"}`}
            >
              {totalUnrealized >= 0 ? "+" : ""}₹
              {totalUnrealized.toLocaleString(undefined, {
                minimumFractionDigits: 2,
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Filter Controls Row */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* 1. Strategy Tabs */}
        <div className="flex items-center gap-2">
          {[
            {
              id: "MINERVINI",
              label: "Minervini Stage-2 VCP",
              count: holdingsData.filter((h) => h.strategy === "MINERVINI")
                .length,
            },
            {
              id: "CONNORS",
              label: "Connors RSI(2) Pullback",
              count: holdingsData.filter((h) => h.strategy === "CONNORS")
                .length,
            },
            {
              id: "ALL",
              label: "Consolidated Portfolio",
              count: holdingsData.length,
            },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveStrategy(tab.id as any)}
              className={`px-3.5 py-2 rounded-md text-xs font-semibold flex items-center gap-2 transition ${
                activeStrategy === tab.id
                  ? "bg-emerald-950/80 border border-emerald-500/70 text-emerald-300 shadow-sm"
                  : "bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:border-slate-700"
              }`}
            >
              {tab.label}
              <span
                className={`text-[10px] px-1.5 py-0.2 rounded-full ${
                  activeStrategy === tab.id
                    ? "bg-emerald-800 text-emerald-100"
                    : "bg-slate-800 text-slate-400"
                }`}
              >
                {tab.count}
              </span>
            </button>
          ))}
        </div>

        {/* 2. Broker Filter Pills */}
        <div className="flex items-center gap-1.5 bg-slate-900/90 p-1 rounded-lg border border-slate-800">
          <div className="flex items-center gap-1 px-2 text-slate-500 text-[11px] font-medium">
            <Filter className="h-3 w-3 text-slate-400" />
            <span>Broker:</span>
          </div>
          {[
            { id: "ALL", label: "All Brokers" },
            { id: "ZERODHA", label: "Zerodha" },
            { id: "UPSTOX", label: "Upstox" },
            { id: "IBKR", label: "IBKR" },
          ].map((b) => (
            <button
              key={b.id}
              onClick={() => setActiveBroker(b.id as any)}
              className={`px-2.5 py-1 rounded text-[11px] font-medium transition ${
                activeBroker === b.id
                  ? "bg-slate-800 text-white shadow-xs border border-slate-700"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {b.label}
            </button>
          ))}
        </div>
      </div>

      {/* Holdings Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 uppercase tracking-wider">
            <tr>
              <th className="p-3.5">Stock</th>
              <th className="p-3.5">Broker</th>
              {activeStrategy === "ALL" && <th className="p-3.5">Strategy</th>}
              <th className="p-3.5">Qty</th>
              <th className="p-3.5">Entry Price</th>
              <th className="p-3.5">Current Price</th>
              <th className="p-3.5">P&L</th>

              {/* Minervini Headers */}
              {activeStrategy === "MINERVINI" && (
                <>
                  <th className="p-3.5">Highest Close</th>
                  <th className="p-3.5">Trailing Stop</th>
                </>
              )}

              {/* Connors Headers */}
              {activeStrategy === "CONNORS" && (
                <>
                  <th className="p-3.5">Days Held</th>
                  <th className="p-3.5">RSI(2) / SMA5</th>
                </>
              )}

              {/* Recommendation header hidden on Consolidated view */}
              {activeStrategy !== "ALL" && (
                <th className="p-3.5">Recommendation</th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {filteredHoldings.length === 0 ? (
              <tr>
                <td colSpan={10} className="p-6 text-center text-slate-500">
                  No positions match the selected strategy and broker filters.
                </td>
              </tr>
            ) : (
              filteredHoldings.map((h) => (
                <tr key={h.id} className="hover:bg-slate-800/50 transition">
                  <td className="p-3.5">
                    <div className="font-semibold text-white">{h.name}</div>
                    <div className="font-mono text-[10px] text-slate-500">
                      {h.ticker}
                    </div>
                  </td>

                  {/* Broker Badge */}
                  <td className="p-3.5">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold border ${getBrokerBadge(h.broker)}`}
                    >
                      {h.broker}
                    </span>
                  </td>

                  {activeStrategy === "ALL" && (
                    <td className="p-3.5">
                      <span className="bg-slate-800 px-2 py-0.5 rounded text-[10px] text-slate-300 font-mono">
                        {h.strategy}
                      </span>
                    </td>
                  )}
                  <td className="p-3.5 font-mono">{h.qty}</td>
                  <td className="p-3.5 font-mono text-slate-300">
                    ₹{h.entryPrice.toFixed(2)}
                  </td>
                  <td className="p-3.5 font-mono font-bold text-white">
                    ₹{h.currentPrice.toFixed(2)}
                  </td>
                  <td className="p-3.5">
                    <div
                      className={`font-semibold font-mono ${h.pnlPct >= 0 ? "text-emerald-400" : "text-rose-400"}`}
                    >
                      {h.pnlPct >= 0 ? "+" : ""}
                      {h.pnlPct.toFixed(1)}%
                    </div>
                    <div className="text-[10px] text-slate-400 font-mono">
                      {h.pnlAmt >= 0 ? "+" : ""}₹{h.pnlAmt.toLocaleString()}
                    </div>
                  </td>

                  {/* Minervini Exit Metrics */}
                  {activeStrategy === "MINERVINI" && (
                    <>
                      <td className="p-3.5 font-mono text-slate-400">
                        ₹{h.highestClose?.toFixed(2)}
                      </td>
                      <td className="p-3.5 font-mono text-amber-400 font-semibold">
                        ₹{h.activeStop?.toFixed(2)}
                      </td>
                    </>
                  )}

                  {/* Connors Exit Metrics */}
                  {activeStrategy === "CONNORS" && (
                    <>
                      <td className="p-3.5 font-mono text-slate-300">
                        {h.daysHeld} / 7 days
                      </td>
                      <td className="p-3.5 font-mono">
                        <span
                          className={
                            h.currentRSI2! > 70
                              ? "text-emerald-400 font-bold"
                              : "text-slate-300"
                          }
                        >
                          RSI: {h.currentRSI2}
                        </span>
                        <div className="text-[10px] text-slate-400">
                          SMA5: ₹{h.sma5?.toFixed(2)}
                        </div>
                      </td>
                    </>
                  )}

                  {/* Action Alert Column (Only on Strategy Tabs) */}
                  {activeStrategy !== "ALL" && (
                    <td className="p-3.5">
                      {h.action === "HOLD" ? (
                        <div className="flex flex-col gap-0.5">
                          <span className="bg-slate-800 text-slate-300 px-2 py-0.5 rounded text-[10px] font-semibold w-fit">
                            HOLD
                          </span>
                          <span className="text-[10px] text-slate-500">
                            {h.reason}
                          </span>
                        </div>
                      ) : (
                        <div className="flex flex-col gap-0.5">
                          <span className="bg-rose-950 text-rose-300 border border-rose-800 px-2 py-0.5 rounded text-[10px] font-bold flex items-center gap-1 w-fit">
                            <AlertCircle className="h-3 w-3 text-rose-400" />{" "}
                            SELL
                          </span>
                          <span className="text-[10px] text-rose-400 font-medium">
                            {h.reason}
                          </span>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
