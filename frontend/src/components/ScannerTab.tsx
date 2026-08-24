"use client";
import { useState } from "react";
import { apiClient } from "@/lib/api";

export function ScannerTab({
  onSelectStock,
}: {
  onSelectStock: (stock: any) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<{ minervini: any[]; connors: any[] }>({
    minervini: [],
    connors: [],
  });
  const [activeStrategy, setActiveStrategy] = useState<"MINERVINI" | "CONNORS">(
    "MINERVINI",
  );

  const handleScan = async () => {
    setLoading(true);
    try {
      const data = await apiClient.runScanner(activeStrategy);
      setResults(data);
    } catch (err) {
      console.error("Scanner error:", err);
    } finally {
      setLoading(false);
    }
  };

  const rows =
    activeStrategy === "MINERVINI"
      ? results.minervini || []
      : results.connors || [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          <button
            onClick={() => setActiveStrategy("MINERVINI")}
            className={`px-3 py-1.5 text-xs rounded font-medium ${activeStrategy === "MINERVINI" ? "bg-emerald-600 text-white" : "bg-zinc-800 text-zinc-400"}`}
          >
            Stage 2 Breakout (Minervini)
          </button>
          <button
            onClick={() => setActiveStrategy("CONNORS")}
            className={`px-3 py-1.5 text-xs rounded font-medium ${activeStrategy === "CONNORS" ? "bg-emerald-600 text-white" : "bg-zinc-800 text-zinc-400"}`}
          >
            Connors RSI(2) Pullback
          </button>
        </div>
        <button
          onClick={handleScan}
          disabled={loading}
          className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs rounded font-medium disabled:opacity-50"
        >
          {loading ? "Running Scan..." : "Run Scanner"}
        </button>
      </div>

      <div className="border border-zinc-800 rounded overflow-hidden">
        <table className="w-full text-left text-xs">
          <thead className="bg-zinc-900 text-zinc-400 border-b border-zinc-800">
            <tr>
              <th className="p-2.5">Symbol</th>
              <th className="p-2.5">Close</th>
              {activeStrategy === "MINERVINI" ? (
                <>
                  <th className="p-2.5">50 SMA</th>
                  <th className="p-2.5">200 SMA</th>
                  <th className="p-2.5">Dist to 52W High</th>
                  <th className="p-2.5">Vol Ratio</th>
                </>
              ) : (
                <>
                  <th className="p-2.5">200 SMA</th>
                  <th className="p-2.5">RSI(2)</th>
                  <th className="p-2.5">Action</th>
                </>
              )}
              <th className="p-2.5 text-right">Execute</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800 font-mono">
            {rows.map((row) => (
              <tr key={row.symbol} className="hover:bg-zinc-900/50">
                <td className="p-2.5 font-bold text-white">{row.symbol}</td>
                <td className="p-2.5">₹{row.close}</td>
                {activeStrategy === "MINERVINI" ? (
                  <>
                    <td className="p-2.5 text-zinc-400">{row.sma50}</td>
                    <td className="p-2.5 text-zinc-400">{row.sma200}</td>
                    <td className="p-2.5 text-emerald-400">
                      {row.dist52wHighPct}%
                    </td>
                    <td className="p-2.5">{row.volumeRatio}x</td>
                  </>
                ) : (
                  <>
                    <td className="p-2.5 text-zinc-400">{row.sma200}</td>
                    <td className="p-2.5 text-rose-400 font-bold">
                      {row.rsi2}
                    </td>
                    <td className="p-2.5 text-emerald-400">{row.action}</td>
                  </>
                )}
                <td className="p-2.5 text-right">
                  <button
                    onClick={() => onSelectStock(row)}
                    className="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[11px]"
                  >
                    Trade
                  </button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="p-4 text-center text-zinc-500">
                  No signals found. Click "Run Scanner" to scan the universe.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
