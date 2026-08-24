"use client";
import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

export function HoldingsTab() {
  const [holdings, setHoldings] = useState<any[]>([]);
  const [strategyFilter, setStrategyFilter] = useState("ALL");
  const [brokerFilter, setBrokerFilter] = useState("ALL");

  const loadHoldings = () => {
    apiClient
      .getHoldings(strategyFilter, brokerFilter)
      .then(setHoldings)
      .catch(console.error);
  };

  useEffect(() => {
    loadHoldings();
  }, [strategyFilter, brokerFilter]);

  return (
    <div className="space-y-4">
      <div className="flex gap-4">
        <select
          value={strategyFilter}
          onChange={(e) => setStrategyFilter(e.target.value)}
          className="bg-zinc-900 border border-zinc-800 text-xs px-2.5 py-1.5 rounded text-white"
        >
          <option value="ALL">All Strategies</option>
          <option value="MINERVINI">Minervini</option>
          <option value="CONNORS">Connors RSI</option>
        </select>
        <select
          value={brokerFilter}
          onChange={(e) => setBrokerFilter(e.target.value)}
          className="bg-zinc-900 border border-zinc-800 text-xs px-2.5 py-1.5 rounded text-white"
        >
          <option value="ALL">All Brokers</option>
          <option value="ZERODHA">Zerodha</option>
          <option value="UPSTOX">Upstox</option>
          <option value="IBKR">IBKR</option>
        </select>
      </div>

      <div className="border border-zinc-800 rounded overflow-hidden">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-zinc-900 text-zinc-400 border-b border-zinc-800">
            <tr>
              <th className="p-2.5">Ticker</th>
              <th className="p-2.5">Broker</th>
              <th className="p-2.5">Qty</th>
              <th className="p-2.5">Avg Entry</th>
              <th className="p-2.5">Current</th>
              <th className="p-2.5">Stop Loss</th>
              <th className="p-2.5">PnL</th>
              <th className="p-2.5">Exit Alert</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {holdings.map((h) => (
              <tr key={h.id} className="hover:bg-zinc-900/50">
                <td className="p-2.5 font-bold text-white">{h.ticker}</td>
                <td className="p-2.5 text-zinc-400">{h.broker}</td>
                <td className="p-2.5">{h.qty}</td>
                <td className="p-2.5">₹{h.entryPrice}</td>
                <td className="p-2.5">₹{h.currentPrice}</td>
                <td className="p-2.5 text-amber-400">₹{h.activeStop}</td>
                <td
                  className={`p-2.5 font-bold ${h.pnlAmt >= 0 ? "text-emerald-400" : "text-rose-400"}`}
                >
                  {h.pnlAmt >= 0 ? "+" : ""}₹{h.pnlAmt} ({h.pnlPct}%)
                </td>
                <td className="p-2.5">
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] ${h.action === "SELL" ? "bg-rose-950 text-rose-400 border border-rose-800" : "bg-zinc-800 text-zinc-400"}`}
                  >
                    {h.action} - {h.reason}
                  </span>
                </td>
              </tr>
            ))}
            {holdings.length === 0 && (
              <tr>
                <td colSpan={8} className="p-4 text-center text-zinc-500">
                  No active positions found in database.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
