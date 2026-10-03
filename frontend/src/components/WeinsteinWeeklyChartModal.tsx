"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  createChart,
  IChartApi,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
} from "lightweight-charts";
import { X, Loader2 } from "lucide-react";

interface WeinsteinWeeklyChartModalProps {
  symbol: string;
  isOpen: boolean;
  onClose: () => void;
}

interface WeinsteinChartPayload {
  symbol: string;
  candles: any[];
  sma10: any[];
  sma30: any[];
  sma40: any[];
  volume: any[];
  mrs: any[];
  macd: any[];
  macd_signal: any[];
  macd_hist: any[];
}

export default function WeinsteinWeeklyChartModal({
  symbol,
  isOpen,
  onClose,
}: WeinsteinWeeklyChartModalProps) {
  const mainChartRef = useRef<HTMLDivElement>(null);
  const macdChartRef = useRef<HTMLDivElement>(null);
  const mrsChartRef = useRef<HTMLDivElement>(null);

  const mainApi = useRef<IChartApi | null>(null);
  const macdApi = useRef<IChartApi | null>(null);
  const mrsApi = useRef<IChartApi | null>(null);

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
          `/api/v1/market-data/chart-data/weinstein-weekly?symbol=${symbol}`,
        );
        if (!res.ok) {
          throw new Error(`Failed to load weekly chart for ${symbol}`);
        }
        const data: WeinsteinChartPayload = await res.json();

        const mainEl = mainChartRef.current;
        const macdEl = macdChartRef.current;
        const mrsEl = mrsChartRef.current;

        if (!isMounted || !mainEl || !macdEl || !mrsEl) return;

        // Cleanup any prior charts before creating new ones
        [mainApi, macdApi, mrsApi].forEach((api) => {
          if (api.current) {
            api.current.remove();
            api.current = null;
          }
        });

        const chartOpts = {
          layout: { background: { color: "#020617" }, textColor: "#94a3b8" },
          grid: {
            vertLines: { color: "#1e293b" },
            horzLines: { color: "#1e293b" },
          },
          timeScale: { borderColor: "#334155", visible: true },
        };

        // 1. Main Price + SMA + Volume Chart (480px)
        const main = createChart(mainEl, {
          ...chartOpts,
          width: mainEl.clientWidth,
          height: 480,
          rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.2 } },
        });
        mainApi.current = main;

        const candleSeries = main.addSeries(CandlestickSeries, {
          upColor: "#22c55e",
          downColor: "#ef4444",
          borderVisible: true,
          wickVisible: true,
        });
        candleSeries.setData(data.candles);

        // SMA10 (Blue), SMA30 (Green), SMA40 (Red)
        if (data.sma10?.length) {
          const s10 = main.addSeries(LineSeries, {
            color: "#3b82f6",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          s10.setData(data.sma10);
        }
        if (data.sma30?.length) {
          const s30 = main.addSeries(LineSeries, {
            color: "#22c55e",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          s30.setData(data.sma30);
        }
        if (data.sma40?.length) {
          const s40 = main.addSeries(LineSeries, {
            color: "#ef4444",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          s40.setData(data.sma40);
        }

        // Volume Pane (Overlay at bottom of Main)
        if (data.volume?.length) {
          const vol = main.addSeries(HistogramSeries, {
            priceScaleId: "",
            priceFormat: { type: "volume" },
            priceLineVisible: false,
            lastValueVisible: false,
          });
          vol.setData(data.volume);
          vol
            .priceScale()
            .applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
        }

        // 2. MACD Pane (150px)
        const macdChart = createChart(macdEl, {
          ...chartOpts,
          width: macdEl.clientWidth,
          height: 150,
          timeScale: { borderColor: "#334155", visible: false },
        });
        macdApi.current = macdChart;

        if (data.macd_hist?.length) {
          const mHist = macdChart.addSeries(HistogramSeries, {
            priceLineVisible: false,
            lastValueVisible: false,
          });
          mHist.setData(data.macd_hist);
        }

        if (data.macd?.length) {
          const mLine = macdChart.addSeries(LineSeries, {
            color: "#38bdf8",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          mLine.setData(data.macd);
        }
        if (data.macd_signal?.length) {
          const mSig = macdChart.addSeries(LineSeries, {
            color: "#f97316",
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          mSig.setData(data.macd_signal);
        }

        // 3. Mansfield RS Pane (130px)
        const mrsChart = createChart(mrsEl, {
          ...chartOpts,
          width: mrsEl.clientWidth,
          height: 130,
          timeScale: { borderColor: "#334155", visible: true },
        });
        mrsApi.current = mrsChart;

        if (data.mrs?.length) {
          const mrsSeries = mrsChart.addSeries(LineSeries, {
            color: "#a855f7",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          mrsSeries.setData(data.mrs);
          mrsSeries.createPriceLine({
            price: 0.0,
            color: "#64748b",
            lineWidth: 1,
            lineStyle: 2,
            title: "0.0",
            axisLabelVisible: false,
          });
        }

        // Synchronize Time Scales across all 3 panes
        // New: Date-based synchronization
        let isSyncing = false;
        const syncCharts = (source: IChartApi, targets: IChartApi[]) => {
          source.timeScale().subscribeVisibleTimeRangeChange((timeRange) => {
            if (!timeRange || isSyncing) return;
            isSyncing = true;
            targets.forEach((target) => {
              try {
                target.timeScale().setVisibleRange(timeRange);
              } catch (_) {}
            });
            isSyncing = false;
          });
        };

        syncCharts(main, [macdChart, mrsChart]);
        syncCharts(macdChart, [main, mrsChart]);
        syncCharts(mrsChart, [main, macdChart]);

        main.timeScale().fitContent();
      } catch (err: any) {
        if (isMounted) setError(err.message || "Failed to render weekly chart");
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchAndRender();

    const handleResize = () => {
      const mainEl = mainChartRef.current;
      if (!mainEl) return;
      const w = mainEl.clientWidth;

      [mainApi, macdApi, mrsApi].forEach((api) => {
        if (api.current) {
          api.current.applyOptions({ width: w });
        }
      });
    };

    window.addEventListener("resize", handleResize);

    return () => {
      isMounted = false;
      window.removeEventListener("resize", handleResize);
      [mainApi, macdApi, mrsApi].forEach((api) => {
        if (api.current) {
          api.current.remove();
          api.current = null;
        }
      });
    };
  }, [isOpen, symbol]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-3 md:p-6 overflow-y-auto">
      <div className="bg-slate-950 border border-slate-800 rounded-xl w-full max-w-[94vw] 2xl:max-w-7xl overflow-hidden shadow-2xl flex flex-col my-auto max-h-[96vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-3.5 border-b border-slate-800 bg-slate-900/50 shrink-0">
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-bold text-white font-mono">{symbol}</h3>
            <span className="text-xs px-2.5 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-mono font-medium">
              Weekly Weinstein Stage Chart
            </span>
            <div className="hidden sm:flex items-center gap-3 text-xs font-mono text-slate-400 pl-4 border-l border-slate-800">
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-blue-500 inline-block" />{" "}
                SMA 10
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-green-500 inline-block" />{" "}
                SMA 30
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-red-500 inline-block" />{" "}
                SMA 40
              </span>
              <span className="flex items-center gap-1.5 border-l border-slate-700 pl-3">
                <span className="h-2.5 w-2.5 rounded-full bg-purple-500 inline-block" />{" "}
                Mansfield RS
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-sky-400 inline-block" />{" "}
                MACD
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1.5 rounded-md hover:bg-slate-800 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Panes Container */}
        <div className="relative p-5 flex flex-col gap-2 overflow-y-auto">
          {loading && (
            <div className="absolute inset-0 bg-slate-950/70 z-10 flex flex-col items-center justify-center gap-2">
              <Loader2 className="h-7 w-7 text-emerald-400 animate-spin" />
              <span className="text-xs text-slate-400 font-mono">
                Loading weekly Weinstein bars...
              </span>
            </div>
          )}
          {error && (
            <div className="p-8 text-center text-rose-400 text-xs font-mono">
              {error}
            </div>
          )}

          {/* Main Chart (Weekly Candles + SMA10, 30, 40 + Volume) */}
          <div ref={mainChartRef} className="w-full h-[480px]" />

          {/* MACD Sub-pane */}
          <div className="border-t border-slate-800 pt-1.5">
            <span className="text-[11px] font-mono text-slate-400 px-1 font-semibold">
              MACD (12, 26, 9)
            </span>
            <div ref={macdChartRef} className="w-full h-[150px]" />
          </div>

          {/* Mansfield RS Sub-pane */}
          <div className="border-t border-slate-800 pt-1.5">
            <span className="text-[11px] font-mono text-slate-400 px-1 font-semibold">
              Mansfield RS vs SPY (52-week, Zero Line)
            </span>
            <div ref={mrsChartRef} className="w-full h-[130px]" />
          </div>
        </div>
      </div>
    </div>
  );
}
