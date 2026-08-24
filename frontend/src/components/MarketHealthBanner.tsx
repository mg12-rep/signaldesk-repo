"use client";
import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

export function MarketHealthBanner() {
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    apiClient
      .getMarketHealth()
      .then(setHealth)
      .catch((err) => console.error("Market health fetch error:", err));
  }, []);

  if (!health)
    return (
      <div className="text-zinc-500 text-xs">Loading market regime...</div>
    );

  const n50 = health["NIFTY 50"];

  return (
    <div className="flex items-center gap-4 bg-zinc-900 border border-zinc-800 px-4 py-2 rounded-md">
      <span className="text-xs text-zinc-400">
        NIFTY 50: <strong className="text-white">{n50?.close}</strong>
      </span>
      <span className="text-xs text-zinc-400">
        50 SMA: <strong className="text-white">{n50?.sma50?.toFixed(2)}</strong>
      </span>
      <span className="text-xs text-zinc-400">
        200 SMA:{" "}
        <strong className="text-white">{n50?.sma200?.toFixed(2)}</strong>
      </span>
      <span
        className={`text-xs px-2 py-0.5 rounded font-mono ${n50?.regime === "BULLISH" ? "bg-emerald-950 text-emerald-400 border border-emerald-800" : "bg-amber-950 text-amber-400 border border-amber-800"}`}
      >
        {n50?.regime}
      </span>
    </div>
  );
}
