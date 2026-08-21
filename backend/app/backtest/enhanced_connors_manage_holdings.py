"""
Larry Connors Pullback Strategy - Holdings Exit Scanner (DB-Driven)
=======================================================================
Same as connors_manage_holdings.py, but pulls price history from the
database via "db_url" / "markets" in config, matching the DB-driven
manage_holdings.py used for the Minervini strategy.

Your holdings list stays a local CSV (Ticker, EntryDate, EntryPrice,
Shares) -- only the price-history source changed.

Run:
    python enhanced_connors_manage_holdings.py --config config_connors_db.json --holdings connors_holdings.csv
"""

import os
import json
import argparse

import numpy as np
import pandas as pd

from app.backtest.enhanced_minervini_backtest import (
    get_db_engine, load_universe_from_db, load_benchmark_from_db,
    compute_index_weighted_return,
)
from enhanced_connors_pullback_backtest import CONNORS_DEFAULT_CONFIG, compute_connors_indicators


def load_holdings(path):
    df = pd.read_csv(path, encoding="utf-8-sig")
    colmap = {}
    for c in df.columns:
        key = str(c).strip().lower()
        if key in ("ticker", "symbol"):
            colmap[c] = "Ticker"
        elif key in ("entrydate", "entry_date", "date"):
            colmap[c] = "EntryDate"
        elif key in ("entryprice", "entry_price", "price"):
            colmap[c] = "EntryPrice"
        elif key in ("shares", "qty", "quantity"):
            colmap[c] = "Shares"
    df = df.rename(columns=colmap)

    needed = {"Ticker", "EntryDate", "EntryPrice", "Shares"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"holdings file missing columns: {missing}")

    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df["EntryDate"] = pd.to_datetime(df["EntryDate"], errors="coerce")
    df["EntryPrice"] = pd.to_numeric(df["EntryPrice"], errors="coerce")
    df["Shares"] = pd.to_numeric(df["Shares"], errors="coerce").astype(int)
    df = df.dropna(subset=["Ticker", "EntryDate", "EntryPrice", "Shares"])
    return df


def evaluate_holding(ticker, df, entry_date, entry_price, shares, cfg):
    df = df[df["Date"] >= entry_date].reset_index(drop=True)
    if df.empty:
        return {"ticker": ticker, "status": "ERROR",
                "note": "no price data on/after EntryDate -- check the date/ticker"}

    hard_stop = entry_price * (1 - cfg["hard_stop_pct"])
    max_hold = cfg["max_holding_days"]
    exit_rsi_thresh = cfg["exit_rsi_threshold"]
    n = len(df)

    def check_exit(row, hold_days):
        if row["Low"] <= hard_stop:
            return "STOP", round(hard_stop, 2)
        if hold_days >= max_hold:
            return "TIME_EXIT", round(row["Close"], 2)
        rsi2 = row.get("RSI2", np.nan)
        if not pd.isna(rsi2) and rsi2 >= exit_rsi_thresh:
            return "RSI_EXIT", round(row["Close"], 2)
        sma_exit = row.get("SMA_exit", np.nan)
        if not pd.isna(sma_exit) and row["Close"] >= sma_exit:
            return "MA_EXIT", round(row["Close"], 2)
        return None, None

    for i in range(n - 1):
        row = df.iloc[i]
        reason, level = check_exit(row, hold_days=i)
        if reason:
            return {
                "ticker": ticker, "status": "SELL_FULL_OVERDUE",
                "reason": f"{reason} condition was met on {row['Date'].date()} (BEFORE today) -- "
                          f"this position likely should already be closed; verify what happened",
                "trigger_date": row["Date"], "trigger_level": level, "shares_to_sell": shares,
            }

    today_row = df.iloc[-1]
    hold_days_today = n - 1
    reason, level = check_exit(today_row, hold_days=hold_days_today)
    if reason:
        return {
            "ticker": ticker, "status": "SELL_FULL", "reason": f"{reason} triggered today",
            "date": today_row["Date"], "trigger_price": level,
            "close": round(today_row["Close"], 2), "shares_to_sell": shares,
        }

    return {
        "ticker": ticker, "status": "HOLD",
        "date": today_row["Date"], "close": round(today_row["Close"], 2),
        "days_held": hold_days_today, "days_until_time_stop": max_hold - hold_days_today,
        "current_stop": round(hard_stop, 2),
        "pct_above_stop": round((today_row["Close"] / hard_stop - 1) * 100, 2),
        "rsi2_now": round(today_row["RSI2"], 1) if not pd.isna(today_row.get("RSI2", np.nan)) else None,
        "exit_rsi_threshold": exit_rsi_thresh,
    }


def main(cfg, holdings_path):
    holdings = load_holdings(holdings_path)
    print(f"Loaded {len(holdings)} holdings from {holdings_path}")

    engine = get_db_engine(cfg["db_url"])
    start_date = cfg.get("start_date")
    end_date = cfg.get("end_date")

    universes = {}
    for market_label, m_cfg in cfg["markets"].items():
        index_symbol_id = m_cfg["index_symbol_id"]
        benchmark_symbol_id = m_cfg.get("benchmark_symbol_id", index_symbol_id)

        universe = load_universe_from_db(engine, index_symbol_id, start_date, end_date)
        if not universe:
            print(f"  [warn] no DB records found for index {index_symbol_id} ({market_label})")
            continue

        index_return_series = None
        idx_df = load_benchmark_from_db(engine, benchmark_symbol_id, start_date, end_date)
        if idx_df is not None and not idx_df.empty:
            index_return_series = compute_index_weighted_return(idx_df)

        print(f"  computing indicators for {market_label} ({len(universe)} tickers)...")
        for t, df in universe.items():
            universe[t] = compute_connors_indicators(df, cfg, index_return_series=index_return_series)
        universes[market_label] = universe

    results = []
    for _, h in holdings.iterrows():
        ticker = h["Ticker"]
        df = None
        for market_label, universe in universes.items():
            if ticker in universe:
                df = universe[ticker]
                break
        if df is None:
            results.append({"ticker": ticker, "status": "ERROR",
                             "note": "ticker not found in any configured market (DB)"})
            continue
        result = evaluate_holding(ticker, df, h["EntryDate"], h["EntryPrice"], int(h["Shares"]), cfg)
        results.append(result)

    status_priority = {"SELL_FULL_OVERDUE": 0, "SELL_FULL": 1, "HOLD": 2, "ERROR": 3}
    results.sort(key=lambda r: status_priority.get(r["status"], 9))

    os.makedirs(cfg["output_dir"], exist_ok=True)
    today_tag = pd.Timestamp.today().strftime("%Y-%m-%d")
    out_path = os.path.join(cfg["output_dir"], f"connors_holdings_recommendations_{today_tag}.csv")
    pd.DataFrame(results).to_csv(out_path, index=False)

    print(f"\nRecommendations (most urgent first) -> {out_path}\n")
    for r in results:
        status = r["status"]
        if status in ("SELL_FULL", "SELL_FULL_OVERDUE"):
            print(f"  [{status}] {r['ticker']}: {r.get('reason','')} -- sell {r.get('shares_to_sell','?')} shares")
        elif status == "HOLD":
            print(f"  [HOLD] {r['ticker']}: day {r.get('days_held')}/{cfg['max_holding_days']}, "
                  f"stop={r.get('current_stop')} ({r.get('pct_above_stop')}% above), RSI2={r.get('rsi2_now')}")
        else:
            print(f"  [ERROR] {r['ticker']}: {r.get('note','')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="config_connors_db.json")
    parser.add_argument("--holdings", type=str, default="connors_holdings.csv")
    args = parser.parse_args()

    cfg = dict(CONNORS_DEFAULT_CONFIG)
    if os.path.exists(args.config):
        with open(args.config) as f:
            cfg.update(json.load(f))
    else:
        print(f"[warn] {args.config} not found, using defaults only.")

    main(cfg, args.holdings)
