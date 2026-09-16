"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  createChart,
  IChartApi,
  CandlestickSeries,
  LineSeries,
} from "lightweight-charts";
import { X, Loader2 } from "lucide-react";

interface Elder75mChartModalProps {
  symbol: string;
  market: "NSE" | "US";
  isOpen: boolean;
  onClose: () => void;
}

interface ChartPayload {
  symbol: string;
  candles: any[];
  ema8: any[];
  ema21: any[];
  sma50: any[];
  sma150: any[];
  sma200: any[];
}

export default function Elder75mChartModal({
  symbol,
  market,
  isOpen,
  onClose,
}: Elder75mChartModalProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !symbol) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    const fetchAndRender = async () => {
      try {
        const res = await fetch(
          `http://localhost:8000/api/v1/market-data/chart-data/75min?symbol=${symbol}&market=${market}`,
        );
        if (!res.ok) {
          throw new Error(`Failed to load chart data for ${symbol}`);
        }
        const data: ChartPayload = await res.json();

        if (!isMounted || !chartContainerRef.current) return;

        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }

        const tz = market === "US" ? "America/New_York" : "Asia/Kolkata";

        const chart = createChart(chartContainerRef.current, {
          width: chartContainerRef.current.clientWidth,
          height: 480,
          layout: {
            background: { color: "#020617" },
            textColor: "#94a3b8",
          },
          grid: {
            vertLines: { color: "#1e293b" },
            horzLines: { color: "#1e293b" },
          },
          localization: {
            // Shows Date + Time on crosshair hover (e.g., "16 Sep, 10:30")
            timeFormatter: (timestamp: number) => {
              const date = new Date(timestamp * 1000);
              return date.toLocaleString("en-IN", {
                timeZone: tz,
                day: "numeric",
                month: "short",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
              });
            },
          },
          timeScale: {
            timeVisible: true,
            secondsVisible: false,
            borderColor: "#334155",
            // Shows Date on day boundaries and Time on intraday steps
            tickMarkFormatter: (timestamp: number, tickMarkType: number) => {
              const date = new Date(timestamp * 1000);
              // tickMarkType: 0 = Year, 1 = Month, 2 = DayOfMonth, 3 = Time, 4 = TimeWithSeconds
              if (tickMarkType <= 2) {
                return date.toLocaleDateString("en-IN", {
                  timeZone: tz,
                  day: "numeric",
                  month: "short",
                });
              }
              return date.toLocaleTimeString("en-IN", {
                timeZone: tz,
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
              });
            },
          },
        });

        chartRef.current = chart;

        // 1. Candlestick Series (RGB Impulse Colors)
        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor: "#22c55e",
          downColor: "#16a34a",
          borderVisible: true,
          wickVisible: true,
        });
        candleSeries.setData(data.candles);

        // 2. Overlaid Moving Averages with custom colors
        if (data.ema8?.length) {
          const ema8 = chart.addSeries(LineSeries, {
            color: "#f97316", // Orange
            lineWidth: 1,
            title: "EMA 8",
          });
          ema8.setData(data.ema8);
        }

        if (data.ema21?.length) {
          const ema21 = chart.addSeries(LineSeries, {
            color: "#a855f7", // Purple
            lineWidth: 1,
            title: "EMA 21",
          });
          ema21.setData(data.ema21);
        }

        if (data.sma50?.length) {
          const sma50 = chart.addSeries(LineSeries, {
            color: "#3b82f6", // Blue
            lineWidth: 2,
            title: "SMA 50",
          });
          sma50.setData(data.sma50);
        }

        if (data.sma150?.length) {
          const sma150 = chart.addSeries(LineSeries, {
            color: "#22c55e", // Green
            lineWidth: 2,
            title: "SMA 150",
          });
          sma150.setData(data.sma150);
        }

        if (data.sma200?.length) {
          const sma200 = chart.addSeries(LineSeries, {
            color: "#ef4444", // Red
            lineWidth: 2,
            title: "SMA 200",
          });
          sma200.setData(data.sma200);
        }

        chart.timeScale().fitContent();
      } catch (err: any) {
        if (isMounted) setError(err.message || "Failed to render chart");
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchAndRender();

    const handleResize = () => {
      if (chartRef.current && chartContainerRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      isMounted = false;
      window.removeEventListener("resize", handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [isOpen, symbol, market]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-950 border border-slate-800 rounded-xl w-full max-w-5xl overflow-hidden shadow-2xl">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-800 bg-slate-900/50">
          <div className="flex items-center gap-3">
            <h3 className="text-base font-bold text-white font-mono">
              {symbol}
            </h3>
            <span className="text-[11px] px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 font-mono">
              75m Elder Impulse
            </span>
            {/* Indicator Legend Bar */}
            <div className="hidden sm:flex items-center gap-3 text-[11px] font-mono text-slate-400 pl-4 border-l border-slate-800">
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-orange-500 inline-block" />{" "}
                EMA 8
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-purple-500 inline-block" />{" "}
                EMA 21
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-blue-500 inline-block" />{" "}
                SMA 50
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-emerald-500 inline-block" />{" "}
                SMA 150
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-rose-500 inline-block" />{" "}
                SMA 200
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-md hover:bg-slate-800 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="relative p-4">
          {loading && (
            <div className="absolute inset-0 bg-slate-950/70 z-10 flex flex-col items-center justify-center gap-2">
              <Loader2 className="h-6 w-6 text-cyan-400 animate-spin" />
              <span className="text-xs text-slate-400 font-mono">
                Loading 75m bars...
              </span>
            </div>
          )}
          {error && (
            <div className="p-8 text-center text-rose-400 text-xs font-mono">
              {error}
            </div>
          )}
          <div ref={chartContainerRef} className="w-full h-[480px]" />
        </div>
      </div>
    </div>
  );
}
