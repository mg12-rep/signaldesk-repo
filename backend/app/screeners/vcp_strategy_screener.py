import argparse
import asyncio
import json
import os
from typing import List, Optional

import numpy as np
import pandas as pd
from app.backtest.minervini_backtest import (
    DEFAULT_CONFIG,
    add_rs_rank,
    compute_index_weighted_return,
    compute_indicators,
    compute_market_health,
    detect_entry_signals,
    trend_template_pass,
)
from app.db.db_adapter import (
    fetch_index_data_from_db,
    fetch_universe_from_db,
)

"""
Minervini VCP - Database-Backed Daily Buy Signal Generator
===========================================================
Scans your PostgreSQL market universe via db_adapter and reports:
  BUY_TODAY               - Entry trigger hit today, trend template AND
                            volume conditions satisfied.
  NEAR_BUY_VOLUME_PENDING - Trigger hit today, trend template OK, volume
                            threshold pending confirmation.
  WATCHLIST               - Valid VCP base active, price hasn't reached trigger.
"""


def scan_ticker(ticker: str, df: pd.DataFrame, cfg: dict):
    """
    Replays the same day-by-day arming/entry logic used in the backtest engine
    for a single ticker to determine its current state as of the latest day.
    """
    setups = detect_entry_signals(df, cfg)
    if not setups:
        return None

    n = len(df)
    last_i = n - 1
    setup_pointer = 0
    armed = None

    for i in range(n):
        row = df.iloc[i]

        if armed is None:
            ptr = setup_pointer
            while ptr < len(setups) and setups[ptr]["confirm_idx"] > i:
                ptr += 1
            if ptr < len(setups) and setups[ptr]["confirm_idx"] <= i:
                armed = setups[ptr]
                setup_pointer = ptr

        if armed is None:
            continue

        age = i - armed["base_start_idx"]
        if age > cfg["max_base_age_days"]:
            armed = None
            setup_pointer += 1
            continue
        if row["Close"] < armed["trough_floor"] * 0.98:
            armed = None
            setup_pointer += 1
            continue

        trigger = armed["entry_trigger"]
        if row["Low"] <= trigger <= row["High"]:
            fill_price = trigger if row["Open"] >= trigger else row["Open"]

            if not trend_template_pass(row, cfg):
                armed = None
                setup_pointer += 1
                continue

            base_vol = df.iloc[armed["base_start_idx"] : i]["Volume"].mean()
            vol_ok = (not pd.isna(base_vol)) and row["Volume"] >= cfg[
                "volume_mult"
            ] * base_vol

            if not vol_ok:
                if i == last_i:
                    rs = row.get("RS_rank", np.nan)
                    return {
                        "status": "NEAR_BUY_VOLUME_PENDING",
                        "ticker": ticker,
                        "date": row["Date"],
                        "trigger_price": round(trigger, 2),
                        "close": round(row["Close"], 2),
                        "volume": int(row["Volume"]),
                        "volume_needed": int(cfg["volume_mult"] * base_vol)
                        if not pd.isna(base_vol)
                        else None,
                        "swing_high": round(armed["swing_high_price"], 2),
                        "rs_rank": None if pd.isna(rs) else round(rs, 1),
                    }
                continue

            if i == last_i:
                rs = row.get("RS_rank", np.nan)
                return {
                    "status": "BUY_TODAY",
                    "ticker": ticker,
                    "date": row["Date"],
                    "trigger_price": round(trigger, 2),
                    "fill_price_est": round(fill_price, 2),
                    "hard_stop": round(fill_price * (1 - cfg["hard_stop_pct"]), 2),
                    "swing_high": round(armed["swing_high_price"], 2),
                    "close": round(row["Close"], 2),
                    "volume": int(row["Volume"]),
                    "rs_rank": None if pd.isna(rs) else round(rs, 1),
                }
            armed = None
            setup_pointer += 1
            continue

    if armed is not None:
        row = df.iloc[last_i]
        age = last_i - armed["base_start_idx"]
        still_valid = (
            age <= cfg["max_base_age_days"]
            and row["Close"] >= armed["trough_floor"] * 0.98
        )
        if still_valid:
            trigger = armed["entry_trigger"]
            rs = row.get("RS_rank", np.nan)
            return {
                "status": "WATCHLIST",
                "ticker": ticker,
                "date": row["Date"],
                "trigger_price": round(trigger, 2),
                "current_close": round(row["Close"], 2),
                "pct_from_trigger": round((row["Close"] / trigger - 1) * 100, 2),
                "swing_high": round(armed["swing_high_price"], 2),
                "base_age_days": int(age),
                "trend_template_pass_now": bool(trend_template_pass(row, cfg)),
                "rs_rank": None if pd.isna(rs) else round(rs, 1),
            }
    return None


def suggest_position_size(fill_price: float, cfg: dict):
    equity = cfg.get("current_equity", cfg.get("starting_capital"))
    risk_amount = equity * cfg["risk_pct_per_trade"]
    risk_per_share = fill_price * cfg["hard_stop_pct"]
    shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
    return shares, shares * fill_price


async def run_vcp_scan_db(
    cfg: dict,
    exchange_code: str = "NSE",
    index_symbol: str = "NIFTY 500",
    filter_index: Optional[str] = None,
    symbols: Optional[List[str]] = None,
):
    """
    Main async runner querying PostgreSQL directly. Supports dynamic index/symbols filtering.
    """
    os.makedirs(cfg.get("output_dir", "outputs"), exist_ok=True)
    as_of_date = cfg.get("as_of_date")

    target_desc = (
        f"Symbols: {len(symbols)}"
        if symbols
        else (f"Index: {filter_index}" if filter_index else "ALL Universe")
    )
    print(f"\n=== Exchange: {exchange_code} | Target: {target_desc} ===")

    # 1. Fetch market data via updated db_adapter
    universe = await fetch_universe_from_db(
        exchange_code=exchange_code,
        days_back=500,
        index_name=filter_index,
        symbols=symbols,
    )
    if not universe:
        print("⚠️ No stock data returned from database. Exiting scan.")
        return {}

    # 2. Fetch Benchmark Index via db_adapter for Market Health
    index_return_series = None
    market_health = None
    idx_df = await fetch_index_data_from_db(index_symbol=index_symbol, days_back=500)

    if idx_df is not None and not idx_df.empty:
        try:
            if as_of_date:
                idx_df = idx_df[idx_df["Date"] <= pd.Timestamp(as_of_date)]
            index_return_series = compute_index_weighted_return(idx_df)
            market_health = compute_market_health(idx_df, cfg)
            n_healthy = int(market_health.sum())
            print(
                f"  Loaded benchmark '{index_symbol}' ({len(idx_df)} rows) -> Market health: {n_healthy}/{len(market_health)} days healthy"
            )
        except Exception as e:
            print(f"  ⚠️ Could not process benchmark index {index_symbol}: {e}")

    # 3. Compute Indicators & RS Ranks
    print(f"  Computing indicators & RS ranks for {len(universe)} tickers...")
    for t, df in universe.items():
        universe[t] = compute_indicators(df, index_return_series=index_return_series)
    add_rs_rank(universe)

    # Liquidity filter
    for t in list(universe.keys()):
        avgvol = (
            universe[t]["AvgVol50"].iloc[-1]
            if "AvgVol50" in universe[t].columns
            else universe[t]["Volume"].tail(50).mean()
        )
        if pd.isna(avgvol) or avgvol < cfg.get("min_avg_volume", 0):
            del universe[t]

    # Historical trimming if as_of_date is provided
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
        print("⚠️ No stocks remaining after applying filters.")
        return {}

    # 4. Market Health Status for latest date
    today = max(df["Date"].iloc[-1] for df in universe.values())
    market_ok = True
    if market_health is not None:
        try:
            market_ok = bool(market_health.asof(today))
        except Exception:
            market_ok = bool(market_health.iloc[-1])

    print(
        f"  As-of date: {today.date()} | Market Filter: {'HEALTHY' if market_ok else 'UNHEALTHY (entries suppressed)'}"
    )

    # 5. Scan Universe
    buys, near_buys, watchlist = [], [], []
    for t, df in universe.items():
        df = df.reset_index(drop=True)
        result = scan_ticker(t, df, cfg)
        if result is None:
            continue
        if result["status"] == "BUY_TODAY":
            (buys if market_ok else watchlist).append(result)
            if not market_ok:
                result["status"] = "WATCHLIST_MARKET_UNHEALTHY"
                result["pct_from_trigger"] = 0.0
        elif result["status"] == "NEAR_BUY_VOLUME_PENDING":
            near_buys.append(result)
        elif result["status"] == "WATCHLIST":
            watchlist.append(result)

    # Position Sizing for Buys
    for b in buys:
        shares, cost = suggest_position_size(b["fill_price_est"], cfg)
        b["suggested_shares"] = shares
        b["suggested_cost"] = round(cost, 2)

    # 6. Save Outputs
    output_dir = cfg.get("output_dir", "outputs")
    date_tag = today.strftime("%Y-%m-%d")
    buys_df = (
        pd.DataFrame(buys).sort_values("rs_rank", ascending=False)
        if buys
        else pd.DataFrame()
    )
    near_df = (
        pd.DataFrame(near_buys).sort_values("rs_rank", ascending=False)
        if near_buys
        else pd.DataFrame()
    )
    watch_df = (
        pd.DataFrame(watchlist).sort_values("pct_from_trigger")
        if watchlist
        else pd.DataFrame()
    )

    buys_df.to_csv(
        os.path.join(output_dir, f"buy_signals_{exchange_code}_{date_tag}.csv"),
        index=False,
    )
    near_df.to_csv(
        os.path.join(output_dir, f"near_buy_signals_{exchange_code}_{date_tag}.csv"),
        index=False,
    )
    watch_df.to_csv(
        os.path.join(output_dir, f"watchlist_{exchange_code}_{date_tag}.csv"),
        index=False,
    )

    print(f"\n🚀 SCAN RESULTS FOR {date_tag}")
    print(f"  BUY_TODAY: {len(buys)} tickers")
    if buys:
        print(
            buys_df[
                ["ticker", "fill_price_est", "hard_stop", "rs_rank", "suggested_shares"]
            ].to_string(index=False)
        )
    print(f"  NEAR_BUY (volume pending): {len(near_buys)} tickers")
    print(f"  WATCHLIST: {len(watchlist)} tickers")

    return {
        "buys": buys,
        "near_buys": near_buys,
        "watchlist": watchlist,
        "as_of_date": date_tag,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minervini VCP Screener - DB Edition")
    parser.add_argument("--config", type=str, default="config.json")
    parser.add_argument(
        "--exchange",
        type=str,
        default="NSE",
        help="Exchange code (e.g. NSE, NYSE, NASDAQ)",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default="MONIFTY500",
        help="Benchmark index symbol for market health",
    )
    parser.add_argument(
        "--filter_index",
        type=str,
        default=None,
        help="Filter universe by index (e.g. RUSSELL 2000, S&P 500)",
    )
    args = parser.parse_args()

    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(args.config):
        with open(args.config) as f:
            cfg.update(json.load(f))

    asyncio.run(
        run_vcp_scan_db(
            cfg=cfg,
            exchange_code=args.exchange,
            index_symbol=args.benchmark,
            filter_index=args.filter_index,
        )
    )
