"use client";

import React, { useState, useEffect } from "react";
import {
  CheckCircle2,
  ShieldCheck,
  X,
  RefreshCw,
  AlertCircle,
} from "lucide-react";

interface CandidateResult {
  name: string;
  ticker: string;
  market: string;
  action: "BUY_TODAY" | "NEAR_BUY" | "WATCH";
  trigger: number;
  stop: number;
  atr: number;
  trailingPts: number;
  shares: number;
  rs: number;
}

export default function StrategyResults() {
  const [results, setResults] = useState<CandidateResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedMarket, setSelectedMarket] = useState<string>("ALL");
  const [selectedStrategy, setSelectedStrategy] = useState<string>("STAGE_2");

  const [selectedStock, setSelectedStock] = useState<CandidateResult | null>(
    null,
  );
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
  const [dispatchError, setDispatchError] = useState<string | null>(null);

  // Inside src/app/results/page.tsx:
  const [customStockPath, setCustomStockPath] = useState<string>("");

  const fetchStrategyResults = async () => {
    setLoading(true);
    setError(null);
    try {
      let url = `http://localhost:8000/api/v1/scanner/run?exchange=${selectedMarket}&strategy=${selectedStrategy}`;
      if (customStockPath.trim()) {
        url += `&custom_stock_file=${encodeURIComponent(customStockPath.trim())}`;
      }
      const res = await fetch(url);
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(
          errData.detail || "Failed to load candidate strategy signals",
        );
      }
      const data = await res.json();
      setResults(data);
    } catch (err: any) {
      setError(err.message || "Failed to retrieve results");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStrategyResults();
  }, [selectedMarket, selectedStrategy]);

  const handleOpenOrder = (stock: CandidateResult) => {
    setSelectedStock(stock);
    setOrderPlaced(false);
    setDispatchError(null);

    const defaultBroker =
      stock.market === "US" || stock.market === "LSE" || stock.market === "TSE"
        ? "IBKR"
        : "ZERODHA";

    setOrderForm({
      broker: defaultBroker,
      orderType: "LIMIT",
      quantity: stock.shares,
      limitPrice: stock.trigger,
      exchange: stock.market === "US" ? "" : stock.market,
      hardStop: stock.stop,
      trailingStopPts: stock.trailingPts,
    });
  };

  const handleDispatchOrder = async () => {
    if (!selectedStock) return;
    setIsOrdering(true);
    setDispatchError(null);

    try {
      const payload = {
        symbol: selectedStock.ticker,
        broker: orderForm.broker,
        order_type: orderForm.orderType,
        quantity: orderForm.quantity,
        price: orderForm.limitPrice,
        exchange: orderForm.exchange,
        stop_loss: orderForm.hardStop,
        trailing_stop_pts: orderForm.trailingStopPts,
      };

      const res = await fetch("http://localhost:8000/api/v1/orders/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Broker order rejected");
      }

      setOrderPlaced(true);
    } catch (err: any) {
      setDispatchError(err.message || "Order placement failed");
    } finally {
      setIsOrdering(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header & Filter Controls */}
      <div className="flex flex-wrap justify-between items-center gap-4">
        <div>
          <h1 className="text-xl font-bold text-white">
            Strategy Execution Results
          </h1>
          <p className="text-slate-400 text-xs mt-1">
            Shortlisted candidates with multi-broker routing and risk-sized
            order tickets
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={selectedMarket}
            onChange={(e) => setSelectedMarket(e.target.value)}
            className="bg-slate-900 border border-slate-800 text-slate-200 text-xs rounded-md px-3 py-2 outline-none focus:border-blue-500"
          >
            <option value="ALL">All Markets</option>
            <option value="US">US Universe</option>
            <option value="NSE">NSE 500</option>
          </select>

          <select
            value={selectedStrategy}
            onChange={(e) => setSelectedStrategy(e.target.value)}
            className="bg-slate-900 border border-slate-800 text-slate-200 text-xs rounded-md px-3 py-2 outline-none focus:border-blue-500"
          >
            <option value="STAGE_2">Minervini Stage 2</option>
            <option value="CONNORS_RSI">Connors RSI</option>
            <option value="MOMENTUM">Momentum Leaders</option>
          </select>

          <button
            onClick={fetchStrategyResults}
            disabled={loading}
            className="bg-slate-800 hover:bg-slate-700 text-slate-200 p-2 rounded-md transition disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-rose-950/40 border border-rose-800 text-rose-300 p-3 rounded-md text-xs flex items-center gap-2">
          <AlertCircle className="h-4 w-4 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Dynamic Candidate Table */}
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
            {loading ? (
              <tr>
                <td colSpan={9} className="p-8 text-center text-slate-400">
                  Scanning database & calculating order sizing...
                </td>
              </tr>
            ) : results.length === 0 ? (
              <tr>
                <td colSpan={9} className="p-8 text-center text-slate-500">
                  No strategy candidates found matching the criteria.
                </td>
              </tr>
            ) : (
              results.map((r) => (
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
                      {r.market === "NSE" ? "₹" : "$"}
                      {r.trigger.toFixed(2)}
                    </div>
                    <div className="text-[10px] font-mono text-rose-400">
                      Stop: {r.market === "NSE" ? "₹" : "$"}
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
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Multi-Broker Order Modal */}
      {selectedStock && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 max-w-lg w-full shadow-2xl space-y-5">
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

            {dispatchError && (
              <div className="bg-rose-950/40 border border-rose-800 text-rose-300 p-2.5 rounded text-xs flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-rose-400 shrink-0" />
                <span>{dispatchError}</span>
              </div>
            )}

            {orderPlaced ? (
              <div className="text-center py-6 space-y-3">
                <CheckCircle2 className="h-12 w-12 text-emerald-400 mx-auto" />
                <h4 className="text-base font-bold text-white">
                  Order Dispatched to {orderForm.broker}
                </h4>
                <p className="text-xs text-slate-400">
                  {orderForm.orderType} Buy for {orderForm.quantity} shares of{" "}
                  {selectedStock.ticker} routed successfully.
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
                <div className="grid grid-cols-2 gap-4">
                  {/* Broker Selection */}
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

                  {/* Order Type */}
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

                  {/* Exchange */}
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

                  {/* Quantity */}
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

                  {/* Limit Price */}
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

                  {/* Hard Stop Loss */}
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

                  {/* Trailing Stop */}
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

                {/* Capital Summary */}
                <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 flex justify-between items-center">
                  <span className="text-slate-400">
                    Total Capital Required:
                  </span>
                  <span className="font-mono font-bold text-white text-sm">
                    {selectedStock.market === "NSE" ? "₹" : "$"}
                    {(orderForm.quantity * orderForm.limitPrice).toLocaleString(
                      undefined,
                      {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      },
                    )}
                  </span>
                </div>

                {/* Submit Actions */}
                <div className="pt-2 flex justify-end gap-2.5">
                  <button
                    onClick={() => setSelectedStock(null)}
                    className="bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-md font-medium text-xs transition"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleDispatchOrder}
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
