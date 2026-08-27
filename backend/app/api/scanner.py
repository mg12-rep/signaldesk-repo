import asyncio
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
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


class ScanCandidate(BaseModel):
    name: str
    ticker: str
    market: str
    action: (
        str  # BUY_TODAY, NEAR_BUY_VOLUME_PENDING, WATCHLIST, WATCHLIST_MARKET_UNHEALTHY
    )
    trigger: float
    stop: float
    atr: float
    trailingPts: float
    shares: int
    rs: float
    swing_high: Optional[float] = None
    volume_needed: Optional[int] = None
    pct_from_trigger: Optional[float] = None


def _run_minervini_scan_sync(
    market: str = "ALL",
    custom_stock_file: Optional[str] = None,
    as_of_date: Optional[str] = None,
) -> List[dict]:
    cfg = dict(DEFAULT_CONFIG)
    cfg["db_url"] = os.getenv("DATABASE_URL", cfg["db_url"]).replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    )

    if custom_stock_file and os.path.exists(custom_stock_file):
        cfg["ticker_filter_file"] = custom_stock_file

    ticker_filter = resolve_ticker_filter(cfg)
    engine = get_db_engine(cfg["db_url"])

    # Determine which markets to scan
    target_markets = {}
    if market == "ALL":
        target_markets = cfg["markets"]
    elif market == "US":
        target_markets = {
            k: v for k, v in cfg["markets"].items() if k in ["SP500", "NASDAQ100"]
        }
    elif market == "NSE":
        target_markets = {k: v for k, v in cfg["markets"].items() if k in ["NIFTY500"]}
    elif market in cfg["markets"]:
        target_markets = {market: cfg["markets"][market]}
    else:
        target_markets = cfg["markets"]

    all_candidates = []

    for market_label, m_cfg in target_markets.items():
        index_symbol_id = m_cfg.get("index_symbol_id")
        exchange_id = m_cfg.get("exchange_id")
        benchmark_symbol_id = m_cfg.get("benchmark_symbol_id", index_symbol_id or 1)

        try:
            universe = load_universe_from_db(
                engine,
                index_symbol_id=index_symbol_id,
                exchange_id=exchange_id,
                start_date=cfg.get("start_date"),
                end_date=cfg.get("end_date"),
            )
        except Exception as e:
            continue

        if not universe:
            continue

        # Benchmark, RS Ranking & Regime Filter
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

        # Compute Technical Indicators on the full universe first
        for t, df in universe.items():
            universe[t] = compute_indicators(
                df, index_return_series=index_return_series
            )
        add_rs_rank(universe)

        # Liquidity filter
        for t in list(universe.keys()):
            avgvol = universe[t]["AvgVol50"].mean()
            if pd.isna(avgvol) or avgvol < cfg["min_avg_volume"]:
                del universe[t]

        # Apply Custom Stock Filter AFTER universe RS ranking
        if ticker_filter:
            universe = {
                t: df for t, df in universe.items() if t.upper() in ticker_filter
            }
            if not universe:
                continue

        if as_of_date:
            cutoff = pd.Timestamp(as_of_date)
            for t in list(universe.keys()):
                df = universe[t]
                df = df[df["Date"] <= cutoff].reset_index(drop=True)
                if len(df) < 260:
                    del universe[t]
                else:
                    universe[t] = df

        if not universe:
            continue

        today = max(df["Date"].iloc[-1] for df in universe.values())
        market_ok = True
        if market_health is not None:
            try:
                market_ok = bool(market_health.asof(today))
            except Exception:
                market_ok = bool(market_health.iloc[-1])

        # Scan each ticker for VCP entry/watchlist
        for t, df in universe.items():
            res = scan_ticker(t, df.reset_index(drop=True), cfg)
            if res is None:
                continue

            # Calculate ATR (14-day)
            last_df = df.iloc[-14:]
            high_low = last_df["High"] - last_df["Low"]
            atr = (
                float(high_low.mean())
                if not high_low.empty
                else float(res.get("close", 0) * 0.02)
            )

            status = res["status"]
            trigger = float(res.get("trigger_price", res.get("close", 0)))
            fill_est = float(res.get("fill_price_est", trigger))
            stop = float(res.get("hard_stop", fill_est * (1 - cfg["hard_stop_pct"])))
            trailing_pts = float(fill_est * cfg["trailing_stop_pct"])
            shares, _ = suggest_position_size(fill_est, cfg)
            rs_val = float(res.get("rs_rank") or 0.0)

            # Regime action mapping
            action = status
            if status == "BUY_TODAY" and not market_ok:
                action = "WATCHLIST_MARKET_UNHEALTHY"

            market_type = "NSE" if "NIFTY" in market_label else "US"

            all_candidates.append(
                {
                    "name": t,
                    "ticker": t,
                    "market": market_type,
                    "action": action,
                    "trigger": round(trigger, 2),
                    "stop": round(stop, 2),
                    "atr": round(atr, 2),
                    "trailingPts": round(trailing_pts, 2),
                    "shares": int(shares),
                    "rs": round(rs_val, 1),
                    "swing_high": res.get("swing_high"),
                    "volume_needed": res.get("volume_needed"),
                    "pct_from_trigger": res.get("pct_from_trigger"),
                }
            )

    # Sort results: BUY_TODAY first, then by RS rank descending
    action_priority = {
        "BUY_TODAY": 0,
        "NEAR_BUY_VOLUME_PENDING": 1,
        "WATCHLIST": 2,
        "WATCHLIST_MARKET_UNHEALTHY": 3,
    }
    all_candidates.sort(key=lambda x: (action_priority.get(x["action"], 4), -x["rs"]))
    return all_candidates


@router.get("/run", response_model=List[ScanCandidate])
async def run_scanner(
    exchange: str = Query("ALL", regex="^(US|NSE|ALL|SP500|NASDAQ100|NIFTY500)$"),
    custom_stock_file: Optional[str] = Query(
        None, description="Path to CSV/TXT custom stock list"
    ),
    as_of_date: Optional[str] = Query(None, description="YYYY-MM-DD cutoff date"),
):
    """
    Executes the Minervini VCP strategy scan using enhanced_generate_buy_signals logic.
    Runs computation in an AnyIO worker thread to keep FastAPI responsive.
    """
    try:
        results = await asyncio.to_thread(
            _run_minervini_scan_sync,
            market=exchange,
            custom_stock_file=custom_stock_file,
            as_of_date=as_of_date,
        )
        return results
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Scanner execution error: {str(e)}"
        )
