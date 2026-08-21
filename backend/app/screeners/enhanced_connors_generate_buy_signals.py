"""
Larry Connors Pullback Strategy - Daily Buy Signal Generator (DB-Driven)
============================================================================
Same as connors_generate_buy_signals.py, but scans tickers straight from
the database via "db_url" / "markets" in config, matching
enhanced_generate_buy_signals.py's pattern for the Minervini strategy.

  BUY_TODAY   - trend filter passed AND Cumulative RSI(2) is below the
                entry threshold on the most recent day in the DB.
  WATCHLIST   - trend filter passes, CumRSI2 close to the threshold but
                hasn't crossed it yet.

Run:
    python enhanced_connors_generate_buy_signals.py --config config_connors_db.json
"""

import argparse
import json
import os

import numpy as np
import pandas as pd
from app.backtest.enhanced_connors_pullback_backtest import (
    CONNORS_DEFAULT_CONFIG,
    compute_connors_indicators,
    trend_filter_pass,
)
from app.backtest.enhanced_minervini_backtest import (
    add_rs_rank,
    compute_index_weighted_return,
    get_db_engine,
    load_benchmark_from_db,
    load_universe_from_db,
)


def suggest_position_size(fill_price, cfg):
    equity = cfg.get("current_equity", cfg.get("starting_capital"))
    risk_amount = equity * cfg["risk_pct_per_trade"]
    risk_per_share = fill_price * cfg["hard_stop_pct"]
    shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
    return shares, shares * fill_price


def scan_ticker(ticker, df, cfg):
    row = df.iloc[-1]
    if pd.isna(row.get("CumRSI2", np.nan)):
        return None
    if not trend_filter_pass(row, cfg):
        return None

    entry_thresh = cfg["entry_cum_rsi_threshold"]
    cum_rsi = row["CumRSI2"]

    if cum_rsi < entry_thresh:
        fill_price = row["Close"]
        return {
            "status": "BUY_TODAY",
            "ticker": ticker,
            "date": row["Date"],
            "close": round(fill_price, 2),
            "rsi2": round(row["RSI2"], 1),
            "cum_rsi2": round(cum_rsi, 1),
            "hard_stop": round(fill_price * (1 - cfg["hard_stop_pct"]), 2),
        }
    elif cum_rsi < entry_thresh + cfg.get("near_miss_buffer", 5.0):
        return {
            "status": "WATCHLIST",
            "ticker": ticker,
            "date": row["Date"],
            "close": round(row["Close"], 2),
            "rsi2": round(row["RSI2"], 1),
            "cum_rsi2": round(cum_rsi, 1),
            "points_from_trigger": round(cum_rsi - entry_thresh, 1),
        }
    return None


def main(cfg):
    os.makedirs(cfg["output_dir"], exist_ok=True)
    engine = get_db_engine(cfg["db_url"])
    as_of_date = cfg.get("as_of_date")
    start_date = cfg.get("start_date")
    end_date = cfg.get("end_date")

    for market_label, m_cfg in cfg["markets"].items():
        index_symbol_id = m_cfg["index_symbol_id"]
        benchmark_symbol_id = m_cfg.get("benchmark_symbol_id", index_symbol_id)

        print(
            f"\n=== Live Signal Scan: {market_label} (index_symbol_id={index_symbol_id}) ==="
        )
        universe = load_universe_from_db(engine, index_symbol_id, start_date, end_date)
        if not universe:
            print(f"  no DB records found for index {index_symbol_id}, skipping.")
            continue

        index_return_series = None
        idx_df = load_benchmark_from_db(
            engine, benchmark_symbol_id, start_date, end_date
        )
        if idx_df is not None and not idx_df.empty:
            index_return_series = compute_index_weighted_return(idx_df)

        print(f"  computing RSI2/CumRSI2 indicators for {len(universe)} tickers...")
        for t, df in universe.items():
            universe[t] = compute_connors_indicators(
                df, cfg, index_return_series=index_return_series
            )

        for t in list(universe.keys()):
            avgvol = universe[t]["Volume"].rolling(50).mean().mean()
            if pd.isna(avgvol) or avgvol < cfg["min_avg_volume"]:
                del universe[t]

        if cfg.get("trend_filter_mode") == "strict":
            add_rs_rank(universe)

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
            print(
                f"  nothing left to scan for {market_label} after filtering, skipping."
            )
            continue

        today = max(df["Date"].iloc[-1] for df in universe.values())
        print(
            f"  as-of date: {today.date()} | trend filter mode: {cfg.get('trend_filter_mode', 'loose')}"
        )

        buys, watchlist = [], []
        for t, df in universe.items():
            df = df.reset_index(drop=True)
            result = scan_ticker(t, df, cfg)
            if result is None:
                continue
            (buys if result["status"] == "BUY_TODAY" else watchlist).append(result)

        for b in buys:
            shares, cost = suggest_position_size(b["close"], cfg)
            b["suggested_shares"] = shares
            b["suggested_cost"] = round(cost, 2)

        date_tag = today.strftime("%Y-%m-%d")
        buys_df = pd.DataFrame(buys).sort_values("cum_rsi2") if buys else pd.DataFrame()
        watch_df = (
            pd.DataFrame(watchlist).sort_values("points_from_trigger")
            if watchlist
            else pd.DataFrame()
        )

        buys_path = os.path.join(
            cfg["output_dir"], f"connors_buy_signals_{market_label}_{date_tag}.csv"
        )
        watch_path = os.path.join(
            cfg["output_dir"], f"connors_watchlist_{market_label}_{date_tag}.csv"
        )
        buys_df.to_csv(buys_path, index=False)
        watch_df.to_csv(watch_path, index=False)

        print(f"\n  BUY_TODAY: {len(buys)} tickers -> {buys_path}")
        if buys:
            print(
                buys_df[
                    ["ticker", "close", "cum_rsi2", "hard_stop", "suggested_shares"]
                ].to_string(index=False)
            )
        print(
            f"\n  WATCHLIST (near threshold): {len(watchlist)} tickers -> {watch_path}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="config_connors_db.json")
    args = parser.parse_args()

    cfg = dict(CONNORS_DEFAULT_CONFIG)
    cfg["current_equity"] = cfg.get("starting_capital", 1_000_000.0)
    cfg["near_miss_buffer"] = 5.0
    if os.path.exists(args.config):
        with open(args.config) as f:
            cfg.update(json.load(f))
    else:
        print(f"[warn] {args.config} not found, using defaults only.")

    main(cfg)
