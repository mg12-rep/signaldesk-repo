import argparse
import json
import os

import numpy as np
import pandas as pd
from app.backtest.enhanced_minervini_backtest import (
    DEFAULT_CONFIG,
    add_rs_rank,
    compute_index_weighted_return,
    compute_indicators,
    compute_market_health,
    detect_entry_signals,
    get_db_engine,
    load_benchmark_from_db,
    load_universe_from_db,
    trend_template_pass,
)

"""
Minervini VCP - Daily Buy Signal Generator
============================================
Scans your stock universe (the same per-ticker CSVs used for backtesting)
and reports, as of the most recent trading day present in the data:

  BUY_TODAY               - entry trigger was hit today, trend template AND
                             volume conditions both satisfied. This is what
                             the backtest engine would have entered.
  NEAR_BUY_VOLUME_PENDING - trigger hit today, trend template OK, but
                             today's volume hasn't reached the 1.25x
                             confirmation threshold yet. Worth a manual look
                             at intraday volume before day's close.
  WATCHLIST                - a valid, still-active VCP base exists with a
                             known entry trigger price, but price hasn't
                             reached it yet. Shows how far away.

This script imports its core logic directly from minervini_backtest.py
(detect_entry_signals, trend_template_pass, compute_market_health, etc.)
so there is NO logic duplication / drift versus what was backtested -
if you tune a parameter in config.json, it affects both scripts identically.

IMPORTANT: This is a signal generator, not a portfolio manager. It does NOT
know what positions you currently hold, so it will re-flag a ticker as
BUY_TODAY even if you already own it - filter that yourself, or extend the
script with a "currently_held" list in config.json if useful.

This is not financial advice - it mechanically applies the rules you
specified. Treat output as a starting shortlist to verify, not an
instruction to trade automatically.

Run:
    python generate_buy_signals.py --config config.json
"""

"""
Minervini VCP - Daily Buy Signal Generator (PostgreSQL / DB-Driven)
===================================================================
Scans active index constituents directly from the database and identifies
BUY_TODAY, NEAR_BUY_VOLUME_PENDING, and WATCHLIST setups.

Run:
    python generate_buy_signals.py --config config.json
"""


def resolve_ticker_filter(cfg):
    """
    Builds the set of tickers to restrict scanning to, from two optional,
    combinable config sources:
      "ticker_filter": ["AAPL", "MSFT", ...]   -- inline list
      "ticker_filter_file": "path/to/file"     -- CSV with a Symbol/Ticker
                                                   column, or a plain text
                                                   file with one ticker per line
    Returns an uppercase set, or None if neither is set (meaning: scan the
    whole universe, unrestricted -- the original/default behavior).
    """
    tickers = set()
    inline = cfg.get("ticker_filter") or []
    tickers.update(str(t).strip().upper() for t in inline if str(t).strip())

    file_path = cfg.get("ticker_filter_file")
    if file_path:
        if not os.path.exists(file_path):
            print(f"  [warn] ticker_filter_file not found: {file_path} (ignoring)")
        else:
            try:
                df = pd.read_csv(file_path, encoding="utf-8-sig")
                col = None
                for c in df.columns:
                    if str(c).strip().lower() in (
                        "symbol",
                        "ticker",
                        "tickers",
                        "symbols",
                    ):
                        col = c
                        break
                if col is not None:
                    tickers.update(df[col].astype(str).str.strip().str.upper())
                else:
                    # no recognizable header -> treat first column as the list
                    tickers.update(df.iloc[:, 0].astype(str).str.strip().str.upper())
            except Exception:
                # fall back to plain text, one ticker per line
                with open(file_path) as f:
                    tickers.update(line.strip().upper() for line in f if line.strip())

    return tickers if tickers else None


def scan_ticker(ticker, df, cfg):
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
        if (
            age > cfg["max_base_age_days"]
            or row["Close"] < armed["trough_floor"] * 0.98
        ):
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
        if (
            age <= cfg["max_base_age_days"]
            and row["Close"] >= armed["trough_floor"] * 0.98
        ):
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


def suggest_position_size(fill_price, cfg):
    equity = cfg.get("current_equity", cfg.get("starting_capital"))
    risk_amount = equity * cfg["risk_pct_per_trade"]
    risk_per_share = fill_price * cfg["hard_stop_pct"]
    shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
    return shares, shares * fill_price


def main(cfg):
    os.makedirs(cfg["output_dir"], exist_ok=True)
    engine = get_db_engine(cfg["db_url"])
    as_of_date = cfg.get("as_of_date")
    ticker_filter = resolve_ticker_filter(cfg)
    if ticker_filter:
        print(
            f"Ticker filter active: restricting scan to {len(ticker_filter)} supplied tickers."
        )

    for market_label, m_cfg in cfg["markets"].items():
        index_symbol_id = m_cfg["index_symbol_id"]
        benchmark_symbol_id = m_cfg.get("benchmark_symbol_id", index_symbol_id)

        print(
            f"\n=== Live Signal Scan: {market_label} (index_symbol_id={index_symbol_id}) ==="
        )
        universe = load_universe_from_db(engine, index_symbol_id)
        if not universe:
            print(f"  no DB records found for index {index_symbol_id}, skipping.")
            continue

        if ticker_filter:
            found_now = {t.upper() for t in universe.keys()} & ticker_filter
            missing = ticker_filter - {t.upper() for t in universe.keys()}
            if missing:
                print(
                    f"  [warn] not found in this market's data folder: {sorted(missing)}"
                )
            print(
                f"  ticker filter: {len(found_now)}/{len(ticker_filter)} requested tickers "
                f"present -> will compute RS against the FULL universe, then restrict scan to these."
            )

        index_return_series = None
        market_health = None
        idx_df = load_benchmark_from_db(engine, benchmark_symbol_id)
        if idx_df is not None and not idx_df.empty:
            index_return_series = compute_index_weighted_return(idx_df)
            market_health = compute_market_health(idx_df, cfg)

        print(f"  computing indicators & RS ranks for {len(universe)} tickers...")
        for t, df in universe.items():
            universe[t] = compute_indicators(
                df, index_return_series=index_return_series
            )
        add_rs_rank(universe)

        for t in list(universe.keys()):
            avgvol = universe[t]["AvgVol50"].mean()
            if pd.isna(avgvol) or avgvol < cfg["min_avg_volume"]:
                del universe[t]
        # NOW apply the ticker shortlist, AFTER RS rank was computed against
        # the full universe -- filtering earlier would make RS_rank a
        # percentile within just the shortlist, which is meaningless for a
        # handful of names. Liquidity filtering above can still legitimately
        # drop a requested ticker if it's genuinely too illiquid to trade.
        if ticker_filter:
            universe = {
                t: df for t, df in universe.items() if t.upper() in ticker_filter
            }
            print(
                f"  scanning {len(universe)} of {len(ticker_filter)} requested tickers "
                f"(others excluded by liquidity filter or not found)"
            )
            if not universe:
                print(
                    f"  none of the requested tickers survived filtering in {data_dir}, skipping."
                )
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

        today = max(df["Date"].iloc[-1] for df in universe.values())
        market_ok = True
        if market_health is not None:
            try:
                market_ok = bool(market_health.asof(today))
            except Exception:
                market_ok = bool(market_health.iloc[-1])

        print(
            f"  as-of date: {today.date()} | market filter: {'HEALTHY' if market_ok else 'UNHEALTHY (new entries suppressed)'}"
        )

        buys, near_buys, watchlist = [], [], []
        for t, df in universe.items():
            result = scan_ticker(t, df.reset_index(drop=True), cfg)
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

        for b in buys:
            shares, cost = suggest_position_size(b["fill_price_est"], cfg)
            b["suggested_shares"] = shares
            b["suggested_cost"] = round(cost, 2)

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

        buys_path = os.path.join(
            cfg["output_dir"], f"buy_signals_{market_label}_{date_tag}.csv"
        )
        near_path = os.path.join(
            cfg["output_dir"], f"near_buy_signals_{market_label}_{date_tag}.csv"
        )
        watch_path = os.path.join(
            cfg["output_dir"], f"watchlist_{market_label}_{date_tag}.csv"
        )

        buys_df.to_csv(buys_path, index=False)
        near_df.to_csv(near_path, index=False)
        watch_df.to_csv(watch_path, index=False)

        print(f"\n  BUY_TODAY: {len(buys)} tickers -> {buys_path}")
        if buys:
            print(
                buys_df[
                    [
                        "ticker",
                        "fill_price_est",
                        "hard_stop",
                        "rs_rank",
                        "suggested_shares",
                    ]
                ].to_string(index=False)
            )
        print(f"\n  NEAR_BUY (volume pending): {len(near_buys)} tickers -> {near_path}")
        print(f"  WATCHLIST: {len(watchlist)} tickers -> {watch_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="config.json")
    args = parser.parse_args()

    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(args.config):
        with open(args.config) as f:
            cfg.update(json.load(f))
    main(cfg)
