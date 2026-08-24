"use client";

import React, { useState, useEffect } from "react";
import axios from "axios";

const API_BASE = "http://localhost:8000/api/v1";

export default function SignalDeskDashboard() {
  const [activeTab, setActiveTab] = useState<
    "scanner" | "holdings" | "backtest"
  >("scanner");
  const [scannerStrategy, setScannerStrategy] = useState<
    "MINERVINI" | "CONNORS"
  >("MINERVINI");

  // Market Health State
  const [healthData, setHealthData] = useState<any>(null);

  // Sync Buttons State
  const [syncingNSE, setSyncingNSE] = useState(false);
  const [syncingUS, setSyncingUS] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");

  // Scanner State
  const [scanning, setScanning] = useState(false);
  const [scanResults, setScanResults] = useState<{
    minervini: any[];
    connors: any[];
  }>({ minervini: [], connors: [] });

  // Holdings State
  const [holdings, setHoldings] = useState<any[]>([]);
  const [strategyFilter, setStrategyFilter] = useState("ALL");
  const [brokerFilter, setBrokerFilter] = useState("ALL");

  // Order Execution Modal State
  const [modalStock, setModalStock] = useState<any | null>(null);
  const [orderBroker, setOrderBroker] = useState<"UPSTOX" | "ZERODHA">(
    "UPSTOX",
  );
  const [orderQty, setOrderQty] = useState<number>(10);
  const [orderPrice, setOrderPrice] = useState<number>(0);
  const [orderSubmitting, setOrderSubmitting] = useState(false);

  // 1. Initial Load: Market Health & Holdings
  useEffect(() => {
    fetchMarketHealth();
    fetchHoldings();
  }, []);

  const fetchMarketHealth = async () => {
    try {
      const res = await axios.get(`${API_BASE}/market-health/`);
      setHealthData(res.data);
    } catch (err) {
      console.error("Failed to load market health:", err);
    }
  };

  const fetchHoldings = async () => {
    try {
      const res = await axios.get(`${API_BASE}/holdings/`, {
        params: { strategy: strategyFilter, broker: brokerFilter },
      });
      setHoldings(res.data);
    } catch (err) {
      console.error("Failed to load holdings:", err);
    }
  };

  useEffect(() => {
    if (activeTab === "holdings") {
      fetchHoldings();
    }
  }, [strategyFilter, brokerFilter, activeTab]);

  // 2. Trigger Sync Handlers
  const handleSyncNSE = async () => {
    setSyncingNSE(true);
    setSyncMsg("Triggering NSE delta sync...");
    try {
      const res = await axios.post(`${API_BASE}/sync/nse`);
      setSyncMsg("✅ " + res.data.message);
      fetchMarketHealth();
    } catch (err: any) {
      setSyncMsg(
        "❌ NSE Sync Failed: " + (err.response?.data?.detail || err.message),
      );
    } finally {
      setSyncingNSE(false);
    }
  };

  const handleSyncUS = async () => {
    setSyncingUS(true);
    setSyncMsg("Triggering US market sync...");
    try {
      const res = await axios.post(`${API_BASE}/sync/us`);
      setSyncMsg("✅ " + res.data.message);
    } catch (err: any) {
      setSyncMsg(
        "❌ US Sync Failed: " + (err.response?.data?.detail || err.message),
      );
    } finally {
      setSyncingUS(false);
    }
  };

  // 3. Scanner Handler
  const handleRunScanner = async () => {
    setScanning(true);
    try {
      const res = await axios.get(`${API_BASE}/scanner/run`, {
        params: { strategy: scannerStrategy },
      });
      setScanResults(res.data);
    } catch (err) {
      console.error("Scanner failed:", err);
    } finally {
      setScanning(false);
    }
  };

  // 4. Open Order Modal
  const handleOpenTrade = (stock: any) => {
    setModalStock(stock);
    setOrderPrice(stock.close);
    setOrderQty(10);
  };

  // 5. Submit Order Handler
  const handleSubmitOrder = async () => {
    if (!modalStock) return;
    setOrderSubmitting(true);
    try {
      const payload = {
        broker: orderBroker,
        symbol: modalStock.symbol,
        exchange: "NSE",
        order_type: "LIMIT",
        quantity: Number(orderQty),
        price: Number(orderPrice),
      };
      const res = await axios.post(`${API_BASE}/orders/place`, payload);
      alert(
        `Order Placed Successfully via ${orderBroker}!\nOrder Info: ${JSON.stringify(res.data)}`,
      );
      setModalStock(null);
      fetchHoldings();
    } catch (err: any) {
      alert(
        "Order Placement Failed: " +
          (err.response?.data?.detail || err.message),
      );
    } finally {
      setOrderSubmitting(false);
    }
  };

  const n50 = healthData?.["NIFTY 50"];
  const n500 = healthData?.["NIFTY 500"];
  const scanRows =
    scannerStrategy === "MINERVINI"
      ? scanResults.minervini || []
      : scanResults.connors || [];

  return (
    <main className="min-h-screen bg-black text-zinc-100 p-6 font-sans">
      {/* Top Header & Market Health Gauge */}
      <header className="flex flex-col md:flex-row items-start md:items-center justify-between pb-6 border-b border-zinc-800 gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            SIGNALDESK{" "}
            <span className="text-[10px] px-2 py-0.5 bg-zinc-800 text-zinc-400 rounded">
              v1.0
            </span>
          </h1>
          <p className="text-xs text-zinc-500 mt-0.5">
            Quantitative Swing Trading & Execution Terminal
          </p>
        </div>

        {/* Market Health Regimes */}
        <div className="flex items-center gap-3 bg-zinc-900 border border-zinc-800 px-4 py-2 rounded-lg text-xs font-mono">
          <div className="flex items-center gap-2">
            <span className="text-zinc-500">NIFTY 50:</span>
            <span className="text-white font-bold">
              {n50?.close ? `₹${n50.close}` : "--"}
            </span>
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] ${n50?.regime === "BULLISH" ? "bg-emerald-950 text-emerald-400 border border-emerald-800" : "bg-amber-950 text-amber-400 border border-amber-800"}`}
            >
              {n50?.regime || "LOADING"}
            </span>
          </div>
          <span className="text-zinc-700">|</span>
          <div className="flex items-center gap-2">
            <span className="text-zinc-500">NIFTY 500:</span>
            <span className="text-white font-bold">
              {n500?.close ? `₹${n500.close}` : "--"}
            </span>
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] ${n500?.regime === "BULLISH" ? "bg-emerald-950 text-emerald-400 border border-emerald-800" : "bg-amber-950 text-amber-400 border border-amber-800"}`}
            >
              {n500?.regime || "LOADING"}
            </span>
          </div>
        </div>

        {/* Data Ingestion Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleSyncNSE}
            disabled={syncingNSE}
            className="px-3 py-1.5 bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-emerald-400 text-xs font-medium rounded transition disabled:opacity-50"
          >
            {syncingNSE ? "Syncing NSE..." : "Sync NSE"}
          </button>
          <button
            onClick={handleSyncUS}
            disabled={syncingUS}
            className="px-3 py-1.5 bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-blue-400 text-xs font-medium rounded transition disabled:opacity-50"
          >
            {syncingUS ? "Syncing US..." : "Sync US"}
          </button>
        </div>
      </header>

      {syncMsg && (
        <div className="mt-3 px-3 py-1.5 bg-zinc-900/80 border border-zinc-800 text-[11px] font-mono text-zinc-300 rounded">
          {syncMsg}
        </div>
      )}

      {/* Main Tab Navigation */}
      <nav className="flex gap-4 mt-6 border-b border-zinc-800">
        <button
          onClick={() => setActiveTab("scanner")}
          className={`pb-2.5 text-xs font-medium tracking-wide uppercase transition ${
            activeTab === "scanner"
              ? "text-emerald-400 border-b-2 border-emerald-500 font-semibold"
              : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          Strategy Scanner
        </button>
        <button
          onClick={() => setActiveTab("holdings")}
          className={`pb-2.5 text-xs font-medium tracking-wide uppercase transition ${
            activeTab === "holdings"
              ? "text-emerald-400 border-b-2 border-emerald-500 font-semibold"
              : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          Holdings & Exit Monitor
        </button>
      </nav>

      {/* TAB 1: STRATEGY SCANNER */}
      {activeTab === "scanner" && (
        <section className="mt-6 space-y-4">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex gap-2">
              <button
                onClick={() => setScannerStrategy("MINERVINI")}
                className={`px-3 py-1.5 text-xs rounded font-medium ${
                  scannerStrategy === "MINERVINI"
                    ? "bg-emerald-600 text-white"
                    : "bg-zinc-900 text-zinc-400 border border-zinc-800"
                }`}
              >
                Minervini Stage 2
              </button>
              <button
                onClick={() => setScannerStrategy("CONNORS")}
                className={`px-3 py-1.5 text-xs rounded font-medium ${
                  scannerStrategy === "CONNORS"
                    ? "bg-emerald-600 text-white"
                    : "bg-zinc-900 text-zinc-400 border border-zinc-800"
                }`}
              >
                Connors RSI(2)
              </button>
            </div>

            <button
              onClick={handleRunScanner}
              disabled={scanning}
              className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium rounded shadow disabled:opacity-50"
            >
              {scanning
                ? "Scanning Database..."
                : `Run ${scannerStrategy === "MINERVINI" ? "Minervini" : "Connors"} Scan`}
            </button>
          </div>

          {/* Scanner Results Table */}
          <div className="border border-zinc-800 rounded-lg overflow-hidden bg-zinc-950">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-zinc-900 text-zinc-400 border-b border-zinc-800">
                <tr>
                  <th className="p-3">Symbol</th>
                  <th className="p-3">Close</th>
                  {scannerStrategy === "MINERVINI" ? (
                    <>
                      <th className="p-3">50 SMA</th>
                      <th className="p-3">200 SMA</th>
                      <th className="p-3">Dist to 52W High</th>
                      <th className="p-3">Vol Ratio</th>
                    </>
                  ) : (
                    <>
                      <th className="p-3">200 SMA</th>
                      <th className="p-3">RSI(2)</th>
                      <th className="p-3">Signal</th>
                    </>
                  )}
                  <th className="p-3 text-right">Execute</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-900">
                {scanRows.map((row) => (
                  <tr
                    key={row.symbol}
                    className="hover:bg-zinc-900/60 transition"
                  >
                    <td className="p-3 font-bold text-white">{row.symbol}</td>
                    <td className="p-3">₹{row.close}</td>
                    {scannerStrategy === "MINERVINI" ? (
                      <>
                        <td className="p-3 text-zinc-400">₹{row.sma50}</td>
                        <td className="p-3 text-zinc-400">₹{row.sma200}</td>
                        <td className="p-3 text-emerald-400">
                          {row.dist52wHighPct}%
                        </td>
                        <td className="p-3">{row.volumeRatio}x</td>
                      </>
                    ) : (
                      <>
                        <td className="p-3 text-zinc-400">₹{row.sma200}</td>
                        <td className="p-3 text-rose-400 font-bold">
                          {row.rsi2}
                        </td>
                        <td className="p-3 text-emerald-400">{row.action}</td>
                      </>
                    )}
                    <td className="p-3 text-right">
                      <button
                        onClick={() => handleOpenTrade(row)}
                        className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[11px] font-medium"
                      >
                        Trade
                      </button>
                    </td>
                  </tr>
                ))}
                {scanRows.length === 0 && !scanning && (
                  <tr>
                    <td colSpan={7} className="p-6 text-center text-zinc-500">
                      No candidates found. Ingest historical data or click "Run
                      Scan".
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* TAB 2: HOLDINGS & EXIT MONITOR */}
      {activeTab === "holdings" && (
        <section className="mt-6 space-y-4">
          <div className="flex gap-3">
            <select
              value={strategyFilter}
              onChange={(e) => setStrategyFilter(e.target.value)}
              className="bg-zinc-900 border border-zinc-800 text-xs px-3 py-1.5 rounded text-white"
            >
              <option value="ALL">All Strategies</option>
              <option value="MINERVINI">Minervini</option>
              <option value="CONNORS">Connors RSI</option>
            </select>
            <select
              value={brokerFilter}
              onChange={(e) => setBrokerFilter(e.target.value)}
              className="bg-zinc-900 border border-zinc-800 text-xs px-3 py-1.5 rounded text-white"
            >
              <option value="ALL">All Brokers</option>
              <option value="ZERODHA">Zerodha</option>
              <option value="UPSTOX">Upstox</option>
            </select>
          </div>

          <div className="border border-zinc-800 rounded-lg overflow-hidden bg-zinc-950">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-zinc-900 text-zinc-400 border-b border-zinc-800">
                <tr>
                  <th className="p-3">Ticker</th>
                  <th className="p-3">Broker</th>
                  <th className="p-3">Qty</th>
                  <th className="p-3">Avg Entry</th>
                  <th className="p-3">Current</th>
                  <th className="p-3">Active Stop</th>
                  <th className="p-3">PnL</th>
                  <th className="p-3">Action Alert</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-900">
                {holdings.map((h) => (
                  <tr key={h.id} className="hover:bg-zinc-900/60 transition">
                    <td className="p-3 font-bold text-white">{h.ticker}</td>
                    <td className="p-3 text-zinc-400">{h.broker}</td>
                    <td className="p-3">{h.qty}</td>
                    <td className="p-3">₹{h.entryPrice}</td>
                    <td className="p-3">₹{h.currentPrice}</td>
                    <td className="p-3 text-amber-400">₹{h.activeStop}</td>
                    <td
                      className={`p-3 font-bold ${h.pnlAmt >= 0 ? "text-emerald-400" : "text-rose-400"}`}
                    >
                      {h.pnlAmt >= 0 ? "+" : ""}₹{h.pnlAmt} ({h.pnlPct}%)
                    </td>
                    <td className="p-3">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] ${
                          h.action === "SELL"
                            ? "bg-rose-950 text-rose-400 border border-rose-800 font-bold"
                            : "bg-zinc-900 text-zinc-400 border border-zinc-800"
                        }`}
                      >
                        {h.action} - {h.reason}
                      </span>
                    </td>
                  </tr>
                ))}
                {holdings.length === 0 && (
                  <tr>
                    <td colSpan={8} className="p-6 text-center text-zinc-500">
                      No active positions currently tracked in PostgreSQL.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* MODAL: ORDER EXECUTION */}
      {modalStock && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center p-4 z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-6 max-w-sm w-full space-y-4">
            <h3 className="text-sm font-bold text-white border-b border-zinc-800 pb-2">
              Dispatch Order: {modalStock.symbol}
            </h3>

            <div className="space-y-3 text-xs">
              <div>
                <label className="text-zinc-400 block mb-1">
                  Execution Broker
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setOrderBroker("UPSTOX")}
                    className={`py-1.5 text-xs font-semibold rounded border ${
                      orderBroker === "UPSTOX"
                        ? "bg-purple-950 text-purple-300 border-purple-700"
                        : "bg-zinc-800 text-zinc-400 border-zinc-700"
                    }`}
                  >
                    Upstox
                  </button>
                  <button
                    type="button"
                    onClick={() => setOrderBroker("ZERODHA")}
                    className={`py-1.5 text-xs font-semibold rounded border ${
                      orderBroker === "ZERODHA"
                        ? "bg-orange-950 text-orange-300 border-orange-700"
                        : "bg-zinc-800 text-zinc-400 border-zinc-700"
                    }`}
                  >
                    Zerodha Kite
                  </button>
                </div>
              </div>

              <div>
                <label className="text-zinc-400 block mb-1">Quantity</label>
                <input
                  type="number"
                  value={orderQty}
                  onChange={(e) => setOrderQty(Number(e.target.value))}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-white font-mono"
                />
              </div>

              <div>
                <label className="text-zinc-400 block mb-1">
                  Limit Price (₹)
                </label>
                <input
                  type="number"
                  step="0.05"
                  value={orderPrice}
                  onChange={(e) => setOrderPrice(Number(e.target.value))}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-white font-mono"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-zinc-800">
              <button
                type="button"
                onClick={() => setModalStock(null)}
                className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded text-xs"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={orderSubmitting}
                onClick={handleSubmitOrder}
                className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs font-semibold disabled:opacity-50"
              >
                {orderSubmitting
                  ? "Dispatching..."
                  : `Submit to ${orderBroker}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
