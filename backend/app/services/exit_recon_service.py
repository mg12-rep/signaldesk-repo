import json
import logging
import os
from typing import Any, Dict, List, Optional

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
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("exit_recon_service")


def evaluate_single_holding(
    ticker: str,
    df: pd.DataFrame,
    entry_date: pd.Timestamp,
    entry_price: float,
    shares: int,
    initial_shares: int,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Replays price history from entry_date to reconstruct current position state
    and produces today's exit/hold recommendation.
    """
    # df = df[df["Date"] >= entry_date].reset_index(drop=True)
    # if df.empty:
    #     return {
    #         "ticker": ticker,
    #         "status": "ERROR",
    #         "reason": "No price data on/after EntryDate",
    #         "urgency": "LOW",
    #     }

    # If bought today and EOD bars aren't published yet:
    if df[df["Date"] >= entry_date].empty:
        latest_bar = df.iloc[-1]
        return {
            "ticker": ticker,
            "status": "HOLD",
            "action": "HOLD",
            "urgency": "LOW",
            "current_price": round(float(latest_bar["Close"]), 2),
            "current_stop": round(float(entry_price * (1 - cfg["hard_stop_pct"])), 2),
            "pct_above_stop": round(
                float(
                    (
                        (
                            latest_bar["Close"]
                            / (entry_price * (1 - cfg["hard_stop_pct"]))
                        )
                        - 1
                    )
                    * 100
                ),
                2,
            ),
            "targets_hit_so_far": "None",
            "next_target_price": round(float(entry_price * 1.20), 2),
            "pct_to_next_target": round(
                float(((entry_price * 1.20 / latest_bar["Close"]) - 1) * 100), 2
            ),
            "trend_template_pass": True,
            "rs_rank": None,
            "note": "Recently added; evaluated with entry price stop.",
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

    # Phase 1: Replay every day BEFORE today to detect overdue exits
    for i in range(n - 1):
        row = df.iloc[i]
        highest_close = max(highest_close, row["Close"])
        for gain_pct, _ in profit_targets:
            if gain_pct not in targets_hit and row["High"] >= entry_price * (
                1 + gain_pct
            ):
                targets_hit.add(gain_pct)

        any_hit = bool(targets_hit)
        trail_pct = trailing_pct_post if any_hit else trailing_pct_pre
        trailing_stop = highest_close * (1 - trail_pct)
        active_stop = max(hard_stop, trailing_stop)

        if row["Low"] <= active_stop:
            which = "Hard stop" if hard_stop >= trailing_stop else "Trailing stop"
            return {
                "ticker": ticker,
                "status": "SELL_FULL_OVERDUE",
                "action": "SELL",
                "urgency": "HIGH",
                "reason": f"{which} was breached on {row['Date'].strftime('%Y-%m-%d')} (before today)",
                "trigger_date": str(row["Date"].date()),
                "trigger_level": round(float(active_stop), 2),
                "shares_to_sell": shares,
                "current_price": round(float(df.iloc[-1]["Close"]), 2),
            }

        ma_val = row.get(exit_ma_col, np.nan)
        if any_hit and not pd.isna(ma_val) and row["Close"] < ma_val:
            return {
                "ticker": ticker,
                "status": "SELL_FULL_OVERDUE",
                "action": "SELL",
                "urgency": "HIGH",
                "reason": f"Close fell below {exit_ma_col} on {row['Date'].strftime('%Y-%m-%d')} (before today)",
                "trigger_date": str(row["Date"].date()),
                "trigger_level": round(float(ma_val), 2),
                "shares_to_sell": shares,
                "current_price": round(float(df.iloc[-1]["Close"]), 2),
            }

    # Phase 2: Evaluate TODAY fresh
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

    # Today Full Exit Stop
    if today_row["Low"] <= active_stop:
        which = "Hard stop" if hard_stop >= trailing_stop else "Trailing stop"
        return {
            "ticker": ticker,
            "status": "SELL_FULL",
            "action": "SELL",
            "urgency": "HIGH",
            "reason": f"{which} breached today",
            "trigger_price": round(float(active_stop), 2),
            "current_price": round(float(today_row["Close"]), 2),
            "shares_to_sell": shares,
        }

    # Today Trend MA breakdown
    ma_val = today_row.get(exit_ma_col, np.nan)
    if any_hit and not pd.isna(ma_val) and today_row["Close"] < ma_val:
        return {
            "ticker": ticker,
            "status": "SELL_FULL",
            "action": "SELL",
            "urgency": "HIGH",
            "reason": f"Close below {exit_ma_col} today",
            "current_price": round(float(today_row["Close"]), 2),
            f"{exit_ma_col}": round(float(ma_val), 2),
            "shares_to_sell": shares,
        }

    # Partial profit target hit
    if newly_hit_today is not None:
        gain_pct, fraction = newly_hit_today
        sell_shares = min(int(initial_shares * fraction), shares)
        if sell_shares > 0:
            return {
                "ticker": ticker,
                "status": "SELL_PARTIAL",
                "action": "TRIM",
                "urgency": "MEDIUM",
                "reason": f"+{int(gain_pct * 100)}% profit target achieved today",
                "target_price": round(float(entry_price * (1 + gain_pct)), 2),
                "current_price": round(float(today_row["Close"]), 2),
                "shares_to_sell": sell_shares,
                "shares_remaining_after": shares - sell_shares,
            }

    # Normal HOLD
    next_target = next((g for g, _ in profit_targets if g not in targets_hit), None)
    rs = today_row.get("RS_rank", np.nan)
    pct_above_stop = round(float((today_row["Close"] / active_stop - 1) * 100), 2)

    return {
        "ticker": ticker,
        "status": "HOLD",
        "action": "HOLD",
        "urgency": "LOW",
        "current_price": round(float(today_row["Close"]), 2),
        "current_stop": round(float(active_stop), 2),
        "pct_above_stop": pct_above_stop,
        "targets_hit_so_far": ", ".join(
            f"+{int(g * 100)}%" for g in sorted(targets_hit)
        )
        or "None",
        "next_target_price": round(float(entry_price * (1 + next_target)), 2)
        if next_target is not None
        else None,
        "pct_to_next_target": round(
            float((entry_price * (1 + next_target) / today_row["Close"] - 1) * 100), 2
        )
        if next_target is not None
        else None,
        "trend_template_pass": bool(trend_template_pass(today_row, cfg))
        if not pd.isna(today_row.get("SMA200", np.nan))
        else None,
        "rs_rank": None if pd.isna(rs) else round(float(rs), 1),
    }


async def run_exit_reconciliation_service(
    db: AsyncSession,
    broker: Optional[str] = "ZERODHA",
    strategy_label: str = "minervini_vcp",
    config_path: str = "config.json",
) -> List[Dict[str, Any]]:
    """
    Asynchronously loads holdings from DB, loads universe/indicator cache,
    and runs the full exit engine.
    """
    # 1. Load config
    cfg = dict(DEFAULT_CONFIG)
    cfg["strategy_label"] = strategy_label
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg.update(json.load(f))

    # 2. Query open holdings
    broker_filter = " AND UPPER(h.broker) = UPPER(:broker)" if broker else ""
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
        WHERE LOWER(h.strategy) = LOWER(:strategy_label)
          AND h.quantity > 0
          {broker_filter}
        ORDER BY s.trading_symbol;
    """)

    params = {"strategy_label": strategy_label}
    if broker:
        params["broker"] = broker.strip().upper()

    res = await db.execute(query, params)
    rows = res.mappings().all()

    if not rows:
        logger.info(f"No open holdings found for {strategy_label} ({broker})")
        return []

    df_holdings = pd.DataFrame(rows)
    df_holdings["Ticker"] = df_holdings["Ticker"].astype(str).str.strip().str.upper()
    df_holdings["EntryDate"] = pd.to_datetime(df_holdings["EntryDate"], errors="coerce")
    df_holdings["EntryPrice"] = pd.to_numeric(
        df_holdings["EntryPrice"], errors="coerce"
    )
    df_holdings["Shares"] = pd.to_numeric(
        df_holdings["Shares"], errors="coerce"
    ).astype(int)
    df_holdings["InitialShares"] = pd.to_numeric(
        df_holdings["InitialShares"], errors="coerce"
    ).astype(int)

    # 3. Load universe and indicators using sync db engine
    engine = get_db_engine(cfg["db_url"])
    start_date = cfg.get("start_date")
    end_date = cfg.get("end_date")

    universes = {}
    for market_label, m_cfg in cfg.get("markets", {}).items():
        index_symbol_id = m_cfg["index_symbol_id"]
        benchmark_symbol_id = m_cfg.get("benchmark_symbol_id", index_symbol_id)

        universe = load_universe_from_db(engine, index_symbol_id, start_date, end_date)
        if not universe:
            continue

        index_return_series = None
        idx_df = load_benchmark_from_db(
            engine, benchmark_symbol_id, start_date, end_date
        )
        if idx_df is not None and not idx_df.empty:
            index_return_series = compute_index_weighted_return(idx_df)

        for t, df in universe.items():
            universe[t] = compute_indicators(
                df, index_return_series=index_return_series
            )
        add_rs_rank(universe)
        universes[market_label] = universe

    # 4. Evaluate each position
    results = []
    for _, h in df_holdings.iterrows():
        ticker = h["Ticker"]
        holding_id = int(h["HoldingId"])
        h_broker = h["Broker"]

        if pd.isna(h["EntryDate"]):
            results.append(
                {
                    "ticker": ticker,
                    "holding_id": holding_id,
                    "broker": h_broker,
                    "status": "ERROR",
                    "reason": "Missing entry_date in database",
                    "urgency": "LOW",
                }
            )
            continue

        df_price = None
        for _, u in universes.items():
            if ticker in u:
                df_price = u[ticker]
                break

        if df_price is None:
            results.append(
                {
                    "ticker": ticker,
                    "holding_id": holding_id,
                    "broker": h_broker,
                    "status": "ERROR",
                    "reason": "Price history not found in database universe",
                    "urgency": "LOW",
                }
            )
            continue

        eval_res = evaluate_single_holding(
            ticker=ticker,
            df=df_price,
            entry_date=h["EntryDate"],
            entry_price=float(h["EntryPrice"]),
            shares=int(h["Shares"]),
            initial_shares=int(h["InitialShares"]),
            cfg=cfg,
        )
        eval_res["holding_id"] = holding_id
        eval_res["broker"] = h_broker
        results.append(eval_res)

    status_priority = {
        "SELL_FULL_OVERDUE": 0,
        "SELL_FULL": 1,
        "SELL_PARTIAL": 2,
        "HOLD": 3,
        "ERROR": 4,
    }
    print("hello babai")
    print(results)

    results.sort(key=lambda r: status_priority.get(r["status"], 9))
    return results
