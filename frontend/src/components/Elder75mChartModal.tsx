"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  createChart,
  IChartApi,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  LineStyle,
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
  pwh?: any[];
  pmh?: any[];
  candles: any[];
  ema8: any[];
  ema21: any[];
  sma50: any[];
  sma150: any[];
  sma200: any[];
  volume?: any[];
  vol_sma20?: any[];
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

  const timeframeLabel = market === "US" ? "65m" : "75m";

  useEffect(() => {
    if (!isOpen || !symbol) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    const fetchAndRender = async () => {
      try {
        const res = await fetch(
          `/api/v1/market-data/chart-data/75min?symbol=${symbol}&market=${market}`,
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
          height: 520,
          layout: {
            background: { color: "#020617" },
            textColor: "#94a3b8",
          },
          grid: {
            vertLines: { color: "#1e293b" },
            horzLines: { color: "#1e293b" },
          },
          rightPriceScale: {
            scaleMargins: {
              top: 0.1,
              bottom: 0.25,
            },
          },
          localization: {
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
            tickMarkFormatter: (timestamp: number, tickMarkType: number) => {
              const date = new Date(timestamp * 1000);
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

        // 1. Candlestick Series (Elder Impulse Candles)
        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor: "#22c55e",
          downColor: "#ef4444",
          borderVisible: true,
          wickVisible: true,
        });
        candleSeries.setData(data.candles);

        // 2. Previous Week High (PWH)
        if (data.pwh?.length) {
          const pwhSeries = chart.addSeries(LineSeries, {
            color: "#38bdf8", // Sky Blue
            lineWidth: 2,
            lineStyle: LineStyle.Dotted,
            title: "PWH",
            priceLineVisible: false,
            lastValueVisible: true,
          });
          pwhSeries.setData(data.pwh);
        }

        // 3. Previous Month High (PMH)
        if (data.pmh?.length) {
          const pmhSeries = chart.addSeries(LineSeries, {
            color: "#22c55e", // Bright Green
            lineWidth: 2,
            lineStyle: LineStyle.Dotted,
            title: "PMH",
            priceLineVisible: false,
            lastValueVisible: true,
          });
          pmhSeries.setData(data.pmh);
        }

        // 4. Overlaid Moving Averages (Disabled priceLineVisible to clear horizontal clutter)
        if (data.ema8?.length) {
          const ema8 = chart.addSeries(LineSeries, {
            color: "#f97316",
            lineWidth: 1,
            title: "EMA 8",
            priceLineVisible: false,
            lastValueVisible: false,
          });
          ema8.setData(data.ema8);
        }

        if (data.ema21?.length) {
          const ema21 = chart.addSeries(LineSeries, {
            color: "#a855f7",
            lineWidth: 1,
            title: "EMA 21",
            priceLineVisible: false,
            lastValueVisible: false,
          });
          ema21.setData(data.ema21);
        }

        if (data.sma50?.length) {
          const sma50 = chart.addSeries(LineSeries, {
            color: "#60a5fa",
            lineWidth: 2,
            title: "SMA 50",
            priceLineVisible: false,
            lastValueVisible: false,
          });
          sma50.setData(data.sma50);
        }

        if (data.sma150?.length) {
          const sma150 = chart.addSeries(LineSeries, {
            color: "#22c55e",
            lineWidth: 2,
            title: "SMA 150",
            priceLineVisible: false,
            lastValueVisible: false,
          });
          sma150.setData(data.sma150);
        }

        if (data.sma200?.length) {
          const sma200 = chart.addSeries(LineSeries, {
            color: "#ef4444",
            lineWidth: 2,
            title: "SMA 200",
            priceLineVisible: false,
            lastValueVisible: false,
          });
          sma200.setData(data.sma200);
        }

        // 5. Volume Sub-Pane
        if (data.volume?.length) {
          const volumeSeries = chart.addSeries(HistogramSeries, {
            priceScaleId: "",
            priceFormat: {
              type: "volume",
            },
            priceLineVisible: false,
            lastValueVisible: false,
          });
          volumeSeries.setData(data.volume);

          volumeSeries.priceScale().applyOptions({
            scaleMargins: {
              top: 0.8,
              bottom: 0,
            },
          });

          if (data.vol_sma20?.length) {
            const volSmaSeries = chart.addSeries(LineSeries, {
              priceScaleId: "",
              color: "#2563eb",
              lineWidth: 2,
              title: "Vol SMA 20",
              priceLineVisible: false,
              lastValueVisible: false,
              priceFormat: {
                type: "volume",
              },
            });
            volSmaSeries.setData(data.vol_sma20);
          }
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
              {timeframeLabel} Elder Impulse
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
                <span className="h-2 w-2 rounded-full bg-blue-400 inline-block" />{" "}
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
              <span className="flex items-center gap-1 border-l border-slate-700 pl-2">
                <span className="h-0.5 w-3 border-t-2 border-dotted border-sky-400 inline-block" />{" "}
                PWH
              </span>
              <span className="flex items-center gap-1">
                <span className="h-0.5 w-3 border-t-2 border-dotted border-emerald-500 inline-block" />{" "}
                PMH
              </span>
              <span className="flex items-center gap-1 border-l border-slate-700 pl-2">
                <span className="h-2 w-2 rounded-full bg-blue-600 inline-block" />{" "}
                Vol SMA 20
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
                Loading {timeframeLabel} bars...
              </span>
            </div>
          )}
          {error && (
            <div className="p-8 text-center text-rose-400 text-xs font-mono">
              {error}
            </div>
          )}
          <div ref={chartContainerRef} className="w-full h-[520px]" />
        </div>
      </div>
    </div>
  );
}