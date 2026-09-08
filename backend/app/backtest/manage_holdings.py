"""
Minervini VCP - Holdings Exit Recommendation Scanner
=======================================================
Reads your current holdings from the `holdings` DB table (not CSV) and,
using the EXACT SAME exit rules as the backtest engine (hard stop,
trailing stop, staged profit targets, wider post-profit trail, final
trend-exit MA), tells you today's recommended action for each position:

    SELL_FULL          - stop-loss (hard or trailing) or trend-exit MA
                          breached TODAY.
    SELL_FULL_OVERDUE  - the exit condition was actually met on an EARLIER
                          day, before today. If you're still holding, this
                          is flagging that the position likely should
                          already have been closed - check what happened.
    SELL_PARTIAL       - a new profit target was reached TODAY. Shows how
                          many shares to sell (based on the fraction of
                          your ORIGINAL position size for that target).
    HOLD               - nothing triggered. Shows the current stop level,
                          % distance to that stop, and the next unhit
                          profit target for context.

This script imports its logic directly from enhanced_minervini_backtest.py
(compute_indicators, add_rs_rank, trend_template_pass, load_universe_from_db,
load_benchmark_from_db, etc.) so there is no drift between what the backtest
simulates and what this reports. Both price history AND your holdings are
now pulled from the same PostgreSQL database (via "db_url", "markets", and
"strategy_label" in config.json) -- no CSV files involved.

HOLDINGS SOURCE: the `holdings` table, filtered to
WHERE strategy = cfg["strategy_label"] (default "minervini_vcp") so this
script only ever evaluates Minervini-strategy positions, not Connors /
mean_reversion positions that live in the same table under a different
exit-rule engine. Optionally also filtered by cfg["broker"] if set.

REQUIRES two columns on `holdings` beyond what's already there:
    entry_date        DATE      -- when the position was actually opened.
                                    Without this, price-history replay
                                    (which is how SELL_FULL_OVERDUE and
                                    profit-target state get reconstructed)
                                    has no starting point. `updated_at`
                                    is NOT a substitute -- it changes on
                                    every broker sync, not just at entry.
    initial_quantity   INTEGER  -- the ORIGINAL position size at entry.
                                    Falls back to `quantity` (treated as
                                    "no partial sale yet") if NULL, but
                                    get this right for positions you've
                                    already partially sold, since it's
                                    what a SELL_PARTIAL share count is
                                    based on.
Rows with a NULL entry_date are skipped with a loud warning rather than
guessed at.

IMPORTANT ASSUMPTION: this script reconstructs a position's state (highest
close since entry, which profit targets have fired) purely by replaying
price history against your config's rules. If your real trading diverged
from the script (e.g. you manually held past a signal, or sold early), the
reconstructed state can drift from reality -- SELL_FULL_OVERDUE is exactly
the signal that tells you to go check that.

Run:
    python manage_holdings.py --config config.json
    (config.json needs "db_url", "markets", and optionally "strategy_label"
    / "broker"; same db_url as the other scripts)
"""

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
    get_db_engine,
    load_benchmark_from_db,
    load_universe_from_db,
    trend_template_pass,
)
from sqlalchemy import text


def load_holdings_from_db(engine, strategy_label, broker=None):
    """
    Loads open positions for a given strategy from the `holdings` table,
    joined to `symbols` for the trading_symbol (to match load_universe_from_db's
    keys). Rows with a NULL entry_date are dropped with a warning, since
    evaluate_holding() cannot reconstruct position state without one.
    """
    broker_filter = ""
    params = {"strategy_label": strategy_label}
    if broker:
        broker_filter = " AND h.broker = :broker"
        params["broker"] = broker

    query = text(f"""
        SELECT
            h.id AS "HoldingId",
            s.trading_symbol AS "Ticker",
            h.entry_date AS "EntryDate",
            h.avg_buy_price AS "EntryPrice",
            h.quantity AS "Shares",
            COALESCE(h.initial_quantity, h.quantity) AS "InitialShares",
            h.broker AS "Broker",
            h.currency AS "Currency"
        FROM holdings h
        JOIN symbols s ON h.symbol_id = s.id
        WHERE h.strategy = :strategy_label
        {broker_filter}
        ORDER BY s.trading_symbol
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)

    if df.empty:
        return df

    missing_entry_date = df["EntryDate"].isna()
    if missing_entry_date.any():
        skipped = df.loc[missing_entry_date, ["Ticker", "Broker", "HoldingId"]]
        print(
            f"  [warn] {missing_entry_date.sum()} holding(s) skipped -- NULL entry_date "
            f"(can't reconstruct position state without it):"
        )
        for _, r in skipped.iterrows():
            print(f"      {r['Ticker']} ({r['Broker']}), holding id={r['HoldingId']}")
        df = df[~missing_entry_date].reset_index(drop=True)

    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df["EntryDate"] = pd.to_datetime(df["EntryDate"], errors="coerce")
    df["EntryPrice"] = pd.to_numeric(df["EntryPrice"], errors="coerce")
    df["Shares"] = pd.to_numeric(df["Shares"], errors="coerce").astype(int)
    df["InitialShares"] = pd.to_numeric(df["InitialShares"], errors="coerce").astype(
        int
    )
    df = df.dropna(subset=["Ticker", "EntryDate", "EntryPrice", "Shares"])
    return df


def evaluate_holding(ticker, df, entry_date, entry_price, shares, initial_shares, cfg):
    """
    Replays price history from entry_date to reconstruct current position
    state. Two phases:
      1. Walk every day EXCEPT the most recent one, purely to build state
         (highest close, which profit targets fired) and detect whether a
         full-exit condition (stop or trend-exit) already triggered on some
         EARLIER day -- if so, that's SELL_FULL_OVERDUE, and we stop there
         (mirrors that a real position would have already been closed).
      2. Only if no earlier full-exit was found, evaluate the MOST RECENT
         day fresh, using state built up through the day before, to produce
         today's actual recommendation.
    """
    df = df[df["Date"] >= entry_date].reset_index(drop=True)
    if df.empty:
        return {
            "ticker": ticker,
            "status": "ERROR",
            "note": "no price data on/after EntryDate -- check the date/ticker",
        }

    hard_stop = entry_price * (1 - cfg["hard_stop_pct"])
    trailing_pct_pre = cfg["trailing_stop_pct"]
    trailing_pct_post = (
        cfg.get("post_profit_trailing_stop_pct") or cfg["trailing_stop_pct"]
    )
    exit_ma_col = cfg.get("final_exit_ma", "SMA50")
    profit_targets = sorted(cfg["profit_targets"], key=lambda x: x[0])

    highest_close = entry_price
    targets_hit = set()
    n = len(df)

    # --- Phase 1: replay every day BEFORE today, looking for an earlier exit ---
    for i in range(n - 1):
        row = df.iloc[i]
        highest_close = max(highest_close, row["Close"])
        for gain_pct, fraction in profit_targets:
            if gain_pct not in targets_hit and row["High"] >= entry_price * (
                1 + gain_pct
            ):
                targets_hit.add(gain_pct)

        any_hit = bool(targets_hit)
        trail_pct = trailing_pct_post if any_hit else trailing_pct_pre
        trailing_stop = highest_close * (1 - trail_pct)
        active_stop = max(hard_stop, trailing_stop)

        if row["Low"] <= active_stop:
            which = "hard stop" if hard_stop >= trailing_stop else "trailing stop"
            return {
                "ticker": ticker,
                "status": "SELL_FULL_OVERDUE",
                "reason": f"{which} was hit on {row['Date'].date()} (BEFORE today) -- "
                f"this position likely should already be closed; verify what happened",
                "trigger_date": row["Date"],
                "trigger_level": round(active_stop, 2),
                "shares_to_sell": shares,
            }
        ma_val = row.get(exit_ma_col, np.nan)
        if any_hit and not pd.isna(ma_val) and row["Close"] < ma_val:
            return {
                "ticker": ticker,
                "status": "SELL_FULL_OVERDUE",
                "reason": f"Close fell below {exit_ma_col} on {row['Date'].date()} (BEFORE today) -- "
                f"this position likely should already be closed; verify what happened",
                "trigger_date": row["Date"],
                "trigger_level": round(ma_val, 2),
                "shares_to_sell": shares,
            }

    # --- Phase 2: no earlier exit found -> evaluate TODAY fresh ---
    today_row = df.iloc[-1]
    highest_close = max(highest_close, today_row["Close"])

    newly_hit_today = None
    for gain_pct, fraction in profit_targets:
        if gain_pct not in targets_hit and today_row["High"] >= entry_price * (
            1 + gain_pct
        ):
            newly_hit_today = (gain_pct, fraction)
            targets_hit.add(gain_pct)
            break

    any_hit = bool(targets_hit)
    trail_pct = trailing_pct_post if any_hit else trailing_pct_pre
    trailing_stop = highest_close * (1 - trail_pct)
    active_stop = max(hard_stop, trailing_stop)

    if today_row["Low"] <= active_stop:
        which = "hard stop" if hard_stop >= trailing_stop else "trailing stop"
        return {
            "ticker": ticker,
            "status": "SELL_FULL",
            "reason": f"{which} hit today",
            "date": today_row["Date"],
            "trigger_price": round(active_stop, 2),
            "close": round(today_row["Close"], 2),
            "shares_to_sell": shares,
        }

    ma_val = today_row.get(exit_ma_col, np.nan)
    if any_hit and not pd.isna(ma_val) and today_row["Close"] < ma_val:
        return {
            "ticker": ticker,
            "status": "SELL_FULL",
            "reason": f"Close below {exit_ma_col} today",
            "date": today_row["Date"],
            "close": round(today_row["Close"], 2),
            f"{exit_ma_col}": round(ma_val, 2),
            "shares_to_sell": shares,
        }

    if newly_hit_today is not None:
        gain_pct, fraction = newly_hit_today
        sell_shares = min(int(initial_shares * fraction), shares)
        if sell_shares > 0:
            return {
                "ticker": ticker,
                "status": "SELL_PARTIAL",
                "reason": f"+{int(gain_pct * 100)}% profit target hit today",
                "date": today_row["Date"],
                "target_price": round(entry_price * (1 + gain_pct), 2),
                "shares_to_sell": sell_shares,
                "shares_remaining_after": shares - sell_shares,
            }

    # nothing triggered -> HOLD, with current context
    next_target = next((g for g, f in profit_targets if g not in targets_hit), None)
    rs = today_row.get("RS_rank", np.nan)
    return {
        "ticker": ticker,
        "status": "HOLD",
        "date": today_row["Date"],
        "close": round(today_row["Close"], 2),
        "current_stop": round(active_stop, 2),
        "pct_above_stop": round((today_row["Close"] / active_stop - 1) * 100, 2),
        "targets_hit_so_far": ", ".join(
            f"+{int(g * 100)}%" for g in sorted(targets_hit)
        )
        or "none",
        "next_target_price": round(entry_price * (1 + next_target), 2)
        if next_target is not None
        else None,
        "pct_to_next_target": round(
            (entry_price * (1 + next_target) / today_row["Close"] - 1) * 100, 2
        )
        if next_target is not None
        else None,
        "trend_template_pass_now": bool(trend_template_pass(today_row, cfg))
        if not pd.isna(today_row.get("SMA200", np.nan))
        else None,
        "rs_rank": None if pd.isna(rs) else round(rs, 1),
    }


def main(cfg):
    engine = get_db_engine(cfg["db_url"])
    strategy_label = cfg.get("strategy_label", "minervini_vcp")
    broker = cfg.get("broker")

    holdings = load_holdings_from_db(engine, strategy_label, broker=broker)
    filt_desc = f"strategy={strategy_label}" + (f", broker={broker}" if broker else "")
    print(f"Loaded {len(holdings)} holdings from DB ({filt_desc})")
    if holdings.empty:
        print("  nothing to evaluate, exiting.")
        return

    start_date = cfg.get("start_date")
    end_date = cfg.get("end_date")

    # Load each market's full universe once (for meaningful RS rank context),
    # compute indicators, then evaluate only the tickers actually held.
    universes = {}
    for market_label, m_cfg in cfg["markets"].items():
        index_symbol_id = m_cfg["index_symbol_id"]
        benchmark_symbol_id = m_cfg.get("benchmark_symbol_id", index_symbol_id)

        universe = load_universe_from_db(engine, index_symbol_id, start_date, end_date)
        if not universe:
            print(
                f"  [warn] no DB records found for index {index_symbol_id} ({market_label})"
            )
            continue

        index_return_series = None
        idx_df = load_benchmark_from_db(
            engine, benchmark_symbol_id, start_date, end_date
        )
        if idx_df is not None and not idx_df.empty:
            index_return_series = compute_index_weighted_return(idx_df)

        print(
            f"  computing indicators & RS ranks for {market_label} ({len(universe)} tickers)..."
        )
        for t, df in universe.items():
            universe[t] = compute_indicators(
                df, index_return_series=index_return_series
            )
        add_rs_rank(universe)
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
            results.append(
                {
                    "ticker": ticker,
                    "status": "ERROR",
                    "note": "ticker not found in any configured market (DB)",
                }
            )
            continue
        result = evaluate_holding(
            ticker,
            df,
            h["EntryDate"],
            h["EntryPrice"],
            int(h["Shares"]),
            int(h["InitialShares"]),
            cfg,
        )
        result["broker"] = h.get("Broker")
        result["holding_id"] = h.get("HoldingId")
        results.append(result)

    status_priority = {
        "SELL_FULL_OVERDUE": 0,
        "SELL_FULL": 1,
        "SELL_PARTIAL": 2,
        "HOLD": 3,
        "ERROR": 4,
    }
    results.sort(key=lambda r: status_priority.get(r["status"], 9))

    os.makedirs(cfg["output_dir"], exist_ok=True)
    today_tag = pd.Timestamp.today().strftime("%Y-%m-%d")
    out_path = os.path.join(
        cfg["output_dir"], f"holdings_recommendations_{today_tag}.csv"
    )
    pd.DataFrame(results).to_csv(out_path, index=False)

    print(f"\nRecommendations (most urgent first) -> {out_path}\n")
    for r in results:
        status = r["status"]
        if status in ("SELL_FULL", "SELL_FULL_OVERDUE"):
            print(
                f"  [{status}] {r['ticker']}: {r.get('reason', '')} -- sell {r.get('shares_to_sell', '?')} shares"
            )
        elif status == "SELL_PARTIAL":
            print(
                f"  [SELL_PARTIAL] {r['ticker']}: {r.get('reason', '')} -- "
                f"sell {r.get('shares_to_sell', '?')} shares, {r.get('shares_remaining_after', '?')} remain"
            )
        elif status == "HOLD":
            print(
                f"  [HOLD] {r['ticker']}: stop={r.get('current_stop')} "
                f"({r.get('pct_above_stop')}% above), targets hit: {r.get('targets_hit_so_far')}, "
                f"RS={r.get('rs_rank')}"
            )
        else:
            print(f"  [ERROR] {r['ticker']}: {r.get('note', '')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="config.json")
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="overrides cfg['strategy_label'], e.g. minervini_vcp",
    )
    parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="optionally restrict to one broker, e.g. ZERODHA",
    )
    args = parser.parse_args()

    cfg = dict(DEFAULT_CONFIG)
    cfg["strategy_label"] = "minervini_vcp"
    if os.path.exists(args.config):
        with open(args.config) as f:
            cfg.update(json.load(f))
    else:
        print(f"[warn] {args.config} not found, using defaults only.")

    if args.strategy:
        cfg["strategy_label"] = args.strategy
    if args.broker:
        cfg["broker"] = args.broker

    main(cfg)
