import os
from typing import List, Optional

import numpy as np
import pandas as pd
from app.backtest.enhanced_generate_buy_signals import (
    resolve_ticker_filter,
    scan_ticker,
    suggest_position_size,
)
from app.backtest.enhanced_minervini_backtest import (
    DEFAULT_CONFIG,
    add_rs_rank,
    compute_index_weighted_return,
    compute_indicators,
    compute_market_health,
    get_db_engine,
    load_benchmark_from_db,
    load_universe_from_db,
)
from app.backtest.enhanced_minervini_config import load_config
from app.screeners.weinstein_screener import run_weinstein_etf_screener
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


class SignalItem(BaseModel):
    status: str
    ticker: str
    date: str
    trigger_price: float
    close: Optional[float] = None
    volume: Optional[int] = None
    rs_rank: Optional[float] = None
    swing_high: Optional[float] = None
    fill_price_est: Optional[float] = None
    hard_stop: Optional[float] = None
    trailing_stop: Optional[float] = None
    atr14: Optional[float] = None
    suggested_shares: Optional[int] = None
    suggested_cost: Optional[float] = None
    volume_needed: Optional[int] = None
    pct_from_trigger: Optional[float] = None
    base_age_days: Optional[int] = None
    stage: Optional[str] = None


class ScannerRunResponse(BaseModel):
    strategy: str
    mode: str
    market_label: str
    market_status: str
    total_universe_count: int
    scanned_count: int
    buy_today: List[SignalItem]
    near_buys: List[SignalItem]
    watchlist: List[SignalItem]


@router.get("/run", response_model=ScannerRunResponse)
def run_scanner_pipeline(
    strategy: str = Query("minervini_vcp"),
    mode: str = Query("UNIVERSE"),
    universe: Optional[str] = Query("NSE_500"),
    custom_path: Optional[str] = Query(None),
    market: str = Query("NSE"),
):
    # -------------------------------------------------------------
    # Stan Weinstein US ETF Screener Dispatch
    # -------------------------------------------------------------
    if strategy == "weinstein_etf":
        raw_candidates = run_weinstein_etf_screener()

        stage2_buys: List[SignalItem] = []
        stage1_watchlist: List[SignalItem] = []

        # Sort all candidates by Mansfield RS descending (highest relative strength first)
        raw_candidates.sort(key=lambda x: x.get("mrs") or 0.0, reverse=True)

        for item in raw_candidates:
            stage_tag = item.get("stage", "STAGE_2_CONTINUATION")
            close_px = item["close"]
            hard_stop_px = item.get("hard_stop", round(close_px * 0.92, 2))

            sig = SignalItem(
                status="BUY_TODAY"
                if stage_tag == "STAGE_2_CONTINUATION"
                else "WATCHLIST",
                ticker=item["symbol"],
                date=pd.Timestamp.today().strftime("%Y-%m-%d"),
                trigger_price=item.get("resistance", close_px),
                close=close_px,
                volume=item.get("volume", 0),
                rs_rank=item.get("mrs"),  # Primary ranking column
                swing_high=item.get("resistance"),
                pct_from_trigger=item.get("distance_sma_pct"),
                fill_price_est=close_px,
                hard_stop=hard_stop_px,
                trailing_stop=item.get("trailing_stop"),
                atr14=item.get("atr14"),
                stage=stage_tag,
            )
            if stage_tag == "STAGE_2_CONTINUATION":
                stage2_buys.append(sig)
            else:
                stage1_watchlist.append(sig)

        return ScannerRunResponse(
            strategy="weinstein_etf",
            mode="UNIVERSE",
            market_label="US_ETFS",
            market_status="ACTIVE",
            total_universe_count=296,
            scanned_count=len(raw_candidates),
            buy_today=stage2_buys,
            near_buys=[],
            watchlist=stage1_watchlist,
        )

    # -------------------------------------------------------------
    # Standard Minervini / VCP Pipeline
    # -------------------------------------------------------------
    cfg = load_config(mode, universe, market)
    cfg["output_dir"] = "output"

    if mode == "CUSTOM_FILE":
        if not custom_path or not os.path.exists(custom_path):
            raise HTTPException(
                status_code=400, detail=f"Custom CSV file not found: {custom_path}"
            )

        cfg["ticker_filter_file"] = custom_path
        if market == "US":
            market_label = "US_CUSTOM"
            cfg["markets"] = {
                market_label: {"index_symbol_id": 559, "benchmark_symbol_id": 559}
            }
        else:
            market_label = "NSE_CUSTOM"
            cfg["markets"] = {
                market_label: {"exchange_id": 1, "benchmark_symbol_id": 2}
            }

    else:
        cfg["ticker_filter_file"] = None
        if universe == "NSE_500":
            market_label = "NIFTY500"
            cfg["markets"] = {
                market_label: {"index_symbol_id": 2, "benchmark_symbol_id": 1}
            }
        elif universe == "NSE_ALL":
            market_label = "NSE_ALL"
            cfg["markets"] = {
                market_label: {"exchange_id": 1, "benchmark_symbol_id": 2}
            }
        elif universe == "SP_500":
            market_label = "SP500"
            cfg["markets"] = {
                market_label: {"index_symbol_id": 559, "benchmark_symbol_id": 559}
            }
        elif universe == "NASDAQ_100":
            market_label = "NASDAQ100"
            cfg["markets"] = {
                market_label: {"index_symbol_id": 2978, "benchmark_symbol_id": 2978}
            }
        elif universe == "US_ETFS":
            market_label = "US_ETFS"
            cfg["markets"] = {
                market_label: {"exchange_id": 12, "benchmark_symbol_id": 5201}
            }
        else:
            raise HTTPException(
                status_code=400, detail=f"Unknown target universe: {universe}"
            )

    engine = get_db_engine(cfg["db_url"])
    m_cfg = cfg["markets"][market_label]
    index_symbol_id = m_cfg.get("index_symbol_id")
    exchange_id = m_cfg.get("exchange_id")
    benchmark_symbol_id = m_cfg.get("benchmark_symbol_id", index_symbol_id or 1)

    universe_data = load_universe_from_db(
        engine,
        index_symbol_id=index_symbol_id,
        exchange_id=exchange_id,
        start_date=cfg.get("start_date"),
        end_date=cfg.get("end_date"),
    )

    if not universe_data:
        return ScannerRunResponse(
            strategy=strategy,
            mode=mode,
            market_label=market_label,
            market_status="NO_DATA",
            total_universe_count=0,
            scanned_count=0,
            buy_today=[],
            near_buys=[],
            watchlist=[],
        )

    total_universe_count = len(universe_data)

    index_return_series = None
    market_health = None
    idx_df = load_benchmark_from_db(
        engine,
        benchmark_symbol_id=benchmark_symbol_id,
        start_date=cfg.get("start_date"),
        end_date=cfg.get("end_date"),
    )
    if idx_df is not None and not idx_df.empty:
        index_return_series = compute_index_weighted_return(idx_df)
        market_health = compute_market_health(idx_df, cfg)

    for t, df in universe_data.items():
        universe_data[t] = compute_indicators(
            df, index_return_series=index_return_series
        )
    add_rs_rank(universe_data)

    for t in list(universe_data.keys()):
        avgvol = universe_data[t]["AvgVol50"].mean()
        if pd.isna(avgvol) or avgvol < cfg["min_avg_volume"]:
            del universe_data[t]

    ticker_filter = resolve_ticker_filter(cfg)
    if ticker_filter:
        universe_data = {
            t: df for t, df in universe_data.items() if t.upper() in ticker_filter
        }

    if not universe_data:
        return ScannerRunResponse(
            strategy=strategy,
            mode=mode,
            market_label=market_label,
            market_status="NO_TICKERS_MATCHED_FILTER",
            total_universe_count=total_universe_count,
            scanned_count=0,
            buy_today=[],
            near_buys=[],
            watchlist=[],
        )

    today = max(df["Date"].iloc[-1] for df in universe_data.values())
    market_ok = True
    if market_health is not None:
        try:
            market_ok = bool(market_health.asof(today))
        except Exception:
            market_ok = bool(market_health.iloc[-1])

    buys, near_buys, watchlist = [], [], []
    for t, df in universe_data.items():
        result = scan_ticker(t, df.reset_index(drop=True), cfg)
        if result is None:
            continue

        result["date"] = (
            str(result["date"].date())
            if hasattr(result["date"], "date")
            else str(result["date"])
        )

        if result["status"] == "BUY_TODAY":
            if market_ok:
                shares, cost = suggest_position_size(result["fill_price_est"], cfg)
                result["suggested_shares"] = shares
                result["suggested_cost"] = round(cost, 2)
                buys.append(result)
            else:
                result["status"] = "WATCHLIST_MARKET_UNHEALTHY"
                result["pct_from_trigger"] = 0.0
                watchlist.append(result)

        elif result["status"] == "NEAR_BUY_VOLUME_PENDING":
            near_buys.append(result)

        elif result["status"] == "WATCHLIST":
            watchlist.append(result)

    buys.sort(key=lambda x: x.get("rs_rank") or 0, reverse=True)
    near_buys.sort(key=lambda x: x.get("rs_rank") or 0, reverse=True)
    watchlist.sort(key=lambda x: x.get("pct_from_trigger") or 999)

    def normalize_signal(item: dict) -> SignalItem:
        if "close" not in item and "current_close" in item:
            item["close"] = item["current_close"]
        if "volume" not in item:
            item["volume"] = 0
        return SignalItem(**item)

    return ScannerRunResponse(
        strategy=strategy,
        mode=mode,
        market_label=market_label,
        market_status="HEALTHY" if market_ok else "UNHEALTHY",
        total_universe_count=total_universe_count,
        scanned_count=len(universe_data),
        buy_today=[normalize_signal(b) for b in buys],
        near_buys=[normalize_signal(nb) for nb in near_buys],
        watchlist=[normalize_signal(w) for w in watchlist],
    )
