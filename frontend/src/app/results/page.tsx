"use client";

import React, { useState } from "react";
import { CheckCircle2, ShieldCheck, X } from "lucide-react";

export default function StrategyResults() {
  const [selectedStock, setSelectedStock] = useState<any>(null);
  const [orderForm, setOrderForm] = useState({
    broker: "ZERODHA",
    orderType: "LIMIT",
    quantity: 1,
    limitPrice: 0,
    exchange: "NSE",
    hardStop: 0,
    trailingStopPts: 0,
  });
  const [isOrdering, setIsOrdering] = useState(false);
  const [orderPlaced, setOrderPlaced] = useState(false);

  const results = [
    {
      name: "Trent Limited",
      ticker: "TRENT",
      market: "NSE",
      action: "BUY_TODAY",
      trigger: 5420.0,
      stop: 4986.4,
      atr: 142.5,
      trailingPts: 433.6,
      shares: 18,
      rs: 96.4,
    },
    {
      name: "Solar Industries",
      ticker: "SOLARINDS",
      market: "NSE",
      action: "BUY_TODAY",
      trigger: 10250.0,
      stop: 9430.0,
      atr: 280.0,
      trailingPts: 820.0,
      shares: 10,
      rs: 92.1,
    },
    {
      name: "NVIDIA Corp",
      ticker: "NVDA",
      market: "US",
      action: "BUY_TODAY",
      trigger: 182.5,
      stop: 167.9,
      atr: 6.4,
      trailingPts: 14.6,
      shares: 35,
      rs: 98.2,
    },
    {
      name: "Vanguard FTSE All-World",
      ticker: "VWRA",
      market: "LSE",
      action: "BUY_TODAY",
      trigger: 132.4,
      stop: 121.8,
      atr: 2.1,
      trailingPts: 10.5,
      shares: 45,
      rs: 84.0,
    },
    {
      name: "Polycab India",
      ticker: "POLYCAB",
      market: "NSE",
      action: "NEAR_BUY",
      trigger: 6850.0,
      stop: 6302.0,
      atr: 165.0,
      trailingPts: 548.0,
      shares: 14,
      rs: 88.5,
    },
  ];

  const handleOpenOrder = (stock: any) => {
    setSelectedStock(stock);
    setOrderPlaced(false);

    // Smart-default broker & exchange based on market
    const defaultBroker =
      stock.market === "US" || stock.market === "LSE" ? "IBKR" : "ZERODHA";
    const defaultExchange = stock.market === "US" ? "" : stock.market;

    setOrderForm({
      broker: defaultBroker,
      orderType: "LIMIT",
      quantity: stock.shares,
      limitPrice: stock.trigger,
      exchange: defaultExchange,
      hardStop: stock.stop,
      trailingStopPts: stock.trailingPts,
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-xl font-bold text-white">
            Strategy Execution Results
          </h1>
          <p className="text-slate-400 text-xs mt-1">
            Shortlisted candidates with multi-broker routing and risk-sized
            order tickets
          </p>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 uppercase tracking-wider">
            <tr>
              <th className="p-3.5">Stock Name</th>
              <th className="p-3.5">Ticker</th>
              <th className="p-3.5">Market</th>
              <th className="p-3.5">Action</th>
              <th className="p-3.5">Trigger / Stop</th>
              <th className="p-3.5">ATR (14)</th>
              <th className="p-3.5">Trailing Pts</th>
              <th className="p-3.5">RS Rank</th>
              <th className="p-3.5 text-right">Execute</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {results.map((r) => (
              <tr key={r.ticker} className="hover:bg-slate-800/50 transition">
                <td className="p-3.5 font-semibold text-white">{r.name}</td>
                <td className="p-3.5 font-mono text-emerald-400 font-bold">
                  {r.ticker}
                </td>
                <td className="p-3.5">
                  <span className="bg-slate-800 px-2 py-0.5 rounded text-[11px] text-slate-300 font-medium">
                    {r.market}
                  </span>
                </td>
                <td className="p-3.5">
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      r.action === "BUY_TODAY"
                        ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                        : "bg-amber-950 text-amber-400 border border-amber-800"
                    }`}
                  >
                    {r.action}
                  </span>
                </td>
                <td className="p-3.5">
                  <div className="font-mono text-white">
                    {r.market === "US" ? "$" : "₹"}
                    {r.trigger.toFixed(2)}
                  </div>
                  <div className="text-[10px] font-mono text-rose-400">
                    Stop: {r.market === "US" ? "$" : "₹"}
                    {r.stop.toFixed(2)}
                  </div>
                </td>
                <td className="p-3.5 text-slate-300 font-mono">
                  {r.atr.toFixed(1)}
                </td>
                <td className="p-3.5 text-slate-300 font-mono">
                  {r.trailingPts.toFixed(1)}
                </td>
                <td className="p-3.5 text-slate-200 font-mono font-bold">
                  {r.rs}
                </td>
                <td className="p-3.5 text-right">
                  {r.action === "BUY_TODAY" && (
                    <button
                      onClick={() => handleOpenOrder(r)}
                      className="bg-emerald-600 hover:bg-emerald-500 text-white px-3.5 py-1.5 rounded font-semibold text-xs transition shadow-sm"
                    >
                      Place Order
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Multi-Broker Order Modal */}
      {selectedStock && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 max-w-lg w-full shadow-2xl space-y-5">
            {/* Modal Header */}
            <div className="flex justify-between items-center border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-5 w-5 text-emerald-400" />
                <div>
                  <h3 className="font-bold text-white text-sm">
                    Order Dispatch Ticket
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    {selectedStock.name} ({selectedStock.ticker})
                  </p>
                </div>
              </div>
              <button
                onClick={() => setSelectedStock(null)}
                className="text-slate-400 hover:text-white transition p-1"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {orderPlaced ? (
              <div className="text-center py-6 space-y-3">
                <CheckCircle2 className="h-12 w-12 text-emerald-400 mx-auto" />
                <h4 className="text-base font-bold text-white">
                  Order Dispatched to {orderForm.broker}
                </h4>
                <p className="text-xs text-slate-400">
                  {orderForm.orderType} Buy for {orderForm.quantity} shares of{" "}
                  {selectedStock.ticker} routed via {orderForm.broker}.
                </p>
                <button
                  onClick={() => setSelectedStock(null)}
                  className="mt-4 bg-slate-800 hover:bg-slate-700 text-xs px-5 py-2 rounded-md text-white font-medium transition"
                >
                  Done
                </button>
              </div>
            ) : (
              <div className="space-y-4 text-xs">
                {/* Inputs Grid */}
                <div className="grid grid-cols-2 gap-4">
                  {/* 1. Target Broker Dropdown */}
                  <div>
                    <label className="block text-slate-400 font-semibold mb-1">
                      Target Broker
                    </label>
                    <select
                      value={orderForm.broker}
                      onChange={(e) =>
                        setOrderForm({ ...orderForm, broker: e.target.value })
                      }
                      className="w-full bg-slate-950 border border-slate-700 rounded-md p-2 text-emerald-400 font-bold outline-none focus:border-emerald-500"
                    >
                      <option value="ZERODHA">Zerodha (Kite)</option>
                      <option value="UPSTOX">Upstox</option>
                      <option value="IBKR">Interactive Brokers (IBKR)</option>
                    </select>
                  </div>

                  {/* 2. Order Type Dropdown */}
                  <div>
                    <label className="block text-slate-400 font-semibold mb-1">
                      Order Type
                    </label>
                    <select
                      value={orderForm.orderType}
                      onChange={(e) =>
                        setOrderForm({
                          ...orderForm,
                          orderType: e.target.value,
                        })
                      }
                      className="w-full bg-slate-950 border border-slate-700 rounded-md p-2 text-white font-medium outline-none focus:border-emerald-500"
                    >
                      <option value="LIMIT">LIMIT</option>
                      <option value="MARKET">MARKET</option>
                    </select>
                  </div>

                  {/* 3. Exchange Dropdown */}
                  <div>
                    <label className="block text-slate-400 font-semibold mb-1">
                      Exchange
                    </label>
                    <select
                      value={orderForm.exchange}
                      onChange={(e) =>
                        setOrderForm({ ...orderForm, exchange: e.target.value })
                      }
                      className="w-full bg-slate-950 border border-slate-700 rounded-md p-2 text-white font-medium outline-none focus:border-emerald-500"
                    >
                      <option value="NSE">NSE</option>
                      <option value="BSE">BSE</option>
                      <option value="LSE">LSE (UCITS ETFs)</option>
                      <option value="">— Blank (US Direct)</option>
                    </select>
                  </div>

                  {/* 4. Quantity Input */}
                  <div>
                    <label className="block text-slate-400 font-semibold mb-1">
                      Quantity (Shares)
                    </label>
                    <input
                      type="number"
                      value={orderForm.quantity}
                      onChange={(e) =>
                        setOrderForm({
                          ...orderForm,
                          quantity: Number(e.target.value),
                        })
                      }
                      className="w-full bg-slate-950 border border-slate-700 rounded-md p-2 text-white font-mono outline-none focus:border-emerald-500"
                    />
                  </div>

                  {/* Limit Price Input */}
                  <div>
                    <label className="block text-slate-400 font-semibold mb-1">
                      {orderForm.orderType === "LIMIT"
                        ? "Limit Price"
                        : "Est. Market Price"}
                    </label>
                    <input
                      type="number"
                      step="0.05"
                      disabled={orderForm.orderType === "MARKET"}
                      value={orderForm.limitPrice}
                      onChange={(e) =>
                        setOrderForm({
                          ...orderForm,
                          limitPrice: Number(e.target.value),
                        })
                      }
                      className="w-full bg-slate-950 border border-slate-700 rounded-md p-2 text-white font-mono outline-none focus:border-emerald-500 disabled:opacity-50"
                    />
                  </div>

                  {/* 5. Hard Stop-Loss */}
                  <div>
                    <label className="block text-rose-400 font-semibold mb-1">
                      Hard Stop Loss
                    </label>
                    <input
                      type="number"
                      step="0.05"
                      value={orderForm.hardStop}
                      onChange={(e) =>
                        setOrderForm({
                          ...orderForm,
                          hardStop: Number(e.target.value),
                        })
                      }
                      className="w-full bg-slate-950 border border-rose-900/60 rounded-md p-2 text-rose-300 font-mono outline-none focus:border-rose-500"
                    />
                  </div>

                  {/* 6. Trailing Stop Loss Points */}
                  <div className="col-span-2">
                    <label className="block text-amber-400 font-semibold mb-1">
                      Trailing Stop (Points)
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      value={orderForm.trailingStopPts}
                      onChange={(e) =>
                        setOrderForm({
                          ...orderForm,
                          trailingStopPts: Number(e.target.value),
                        })
                      }
                      className="w-full bg-slate-950 border border-amber-900/60 rounded-md p-2 text-amber-300 font-mono outline-none focus:border-amber-500"
                    />
                  </div>
                </div>

                {/* Summary Box */}
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 flex justify-between items-center">
                  <span className="text-slate-400">
                    Total Capital Required:
                  </span>
                  <span className="font-mono font-bold text-white text-sm">
                    {selectedStock.market === "US" ? "$" : "₹"}
                    {(orderForm.quantity * orderForm.limitPrice).toLocaleString(
                      undefined,
                      { minimumFractionDigits: 2, maximumFractionDigits: 2 },
                    )}
                  </span>
                </div>

                {/* Actions */}
                <div className="pt-2 flex justify-end gap-2.5">
                  <button
                    onClick={() => setSelectedStock(null)}
                    className="bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-md font-medium text-xs transition"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => {
                      setIsOrdering(true);
                      setTimeout(() => {
                        setIsOrdering(false);
                        setOrderPlaced(true);
                      }, 700);
                    }}
                    disabled={isOrdering}
                    className="bg-emerald-600 hover:bg-emerald-500 text-white font-semibold px-5 py-2 rounded-md text-xs flex items-center gap-1.5 transition disabled:opacity-50"
                  >
                    {isOrdering
                      ? "Routing Order..."
                      : `Submit to ${orderForm.broker}`}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
