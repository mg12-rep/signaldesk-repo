"""
Larry Connors Pullback Strategy - Backtest Engine (PostgreSQL / DB-Driven)
=============================================================================
Same strategy logic as connors_pullback_backtest.py, but reads price history
directly from the same PostgreSQL database used by
enhanced_minervini_backtest.py / enhanced_generate_buy_signals.py, via
"db_url" and "markets" in config (instead of "data_dirs" / "index_files").

Reuses strategy-agnostic infrastructure directly from
app.backtest.enhanced_minervini_backtest: get_db_engine, load_universe_from_db,
load_benchmark_from_db, compute_indicators, add_rs_rank, trend_template_pass,
compute_index_weighted_return, Trade, sweep_cash, save_trade_log_by_year,
compute_summary_stats, print_summary_stats. This also means the DB path
automatically inherits the pattern-based split-detection safety net baked
into load_universe_from_db/load_benchmark_from_db -- no extra work needed.

See connors_pullback_backtest.py's module docstring for the full strategy
description and documented assumptions (close-based execution, Wilder RSI,
trend_filter_mode options, etc.) -- unchanged here, only the data source
changed.

Run:  python enhanced_connors_pullback_backtest.py --config config_connors_db.json
"""

import argparse
import json
import os

import numpy as np
import pandas as pd
from app.backtest.enhanced_minervini_backtest import (
    Trade,
    add_rs_rank,
    compute_index_weighted_return,
    compute_indicators,
    compute_summary_stats,
    get_db_engine,
    load_benchmark_from_db,
    load_universe_from_db,
    print_summary_stats,
    save_trade_log_by_year,
    sweep_cash,
    trend_template_pass,
)

CONNORS_DEFAULT_CONFIG = {
    "db_url": "postgresql+psycopg://signaldesk_user:signaldesk123@localhost:5432/signaldesk",
    "markets": {},
    "output_dir": "output_connors",
    "start_date": None,
    "end_date": None,
    "starting_capital": 1_000_000.0,
    "reinvest_fraction": 1.0,
    "trend_filter_mode": "loose",  # "loose" | "ma_stack" | "strict"
    "rs_rank_threshold": 70,
    "min_pct_above_52w_low": 0.30,
    "max_pct_below_52w_high": 0.25,
    "rsi_period": 2,
    "cum_days": 2,
    "entry_cum_rsi_threshold": 10.0,
    "exit_rsi_threshold": 65.0,
    "exit_ma_period": 5,
    "max_holding_days": 10,
    "hard_stop_pct": 0.06,
    "risk_pct_per_trade": 0.02,
    "min_avg_volume": 50_000,
}


def compute_rsi(close, period=2):
    """Standard Wilder-smoothed RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0)
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return rsi


def compute_connors_indicators(df, cfg, index_return_series=None):
    df = compute_indicators(df, index_return_series=index_return_series)
    df["RSI2"] = compute_rsi(df["Close"], period=cfg["rsi_period"])
    df["CumRSI2"] = df["RSI2"].rolling(cfg["cum_days"]).sum()
    df["SMA_exit"] = df["Close"].rolling(cfg["exit_ma_period"]).mean()
    return df


def trend_filter_pass(row, cfg):
    mode = cfg.get("trend_filter_mode", "loose")
    sma200 = row.get("SMA200", np.nan)
    if pd.isna(sma200):
        return False
    if mode == "loose":
        return row["Close"] > sma200
    elif mode == "ma_stack":
        sma50, sma150 = row.get("SMA50", np.nan), row.get("SMA150", np.nan)
        if pd.isna(sma50) or pd.isna(sma150):
            return False
        return row["Close"] > sma50 > sma150 > sma200
    elif mode == "strict":
        return trend_template_pass(row, cfg)
    else:
        raise ValueError(
            f"Unknown trend_filter_mode: {mode!r} "
            f"(expected 'loose', 'ma_stack', or 'strict')"
        )


class Position:
    __slots__ = [
        "ticker",
        "entry_date",
        "entry_price",
        "shares",
        "hard_stop",
        "hold_days",
    ]

    def __init__(self, ticker, entry_date, entry_price, shares, hard_stop):
        self.ticker = ticker
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares
        self.hard_stop = hard_stop
        self.hold_days = 0


def run_backtest(universe, cfg, market_label=""):
    print(
        f"[{market_label}] computing RSI2/CumRSI2 indicators for {len(universe)} tickers..."
    )
    for t in list(universe.keys()):
        avgvol = universe[t]["Volume"].rolling(50).mean().mean()
        if pd.isna(avgvol) or avgvol < cfg["min_avg_volume"]:
            del universe[t]

    if cfg.get("trend_filter_mode") == "strict":
        add_rs_rank(universe)

    all_dates = sorted(set().union(*[set(df["Date"]) for df in universe.values()]))
    ticker_dfidx = {t: df.set_index("Date") for t, df in universe.items()}
    ticker_posidx = {
        t: {d: i for i, d in enumerate(df["Date"])} for t, df in universe.items()
    }

    cash = cfg["starting_capital"]
    bank_balance = 0.0
    open_positions = {}
    trade_log = []
    equity_curve = []

    print(f"[{market_label}] running simulation over {len(all_dates)} trading days...")
    for date in all_dates:
        for t in list(open_positions.keys()):
            if date not in ticker_dfidx[t].index:
                continue
            row = ticker_dfidx[t].loc[date]
            pos = open_positions[t]
            pos.hold_days += 1

            exit_reason, fill = None, None
            if row["Low"] <= pos.hard_stop:
                exit_reason = "STOP"
                fill = (
                    min(row["Open"], pos.hard_stop)
                    if row["Open"] < pos.hard_stop
                    else pos.hard_stop
                )
            elif pos.hold_days >= cfg["max_holding_days"]:
                exit_reason = "TIME_EXIT"
                fill = row["Close"]
            elif (
                not pd.isna(row.get("RSI2", np.nan))
                and row["RSI2"] >= cfg["exit_rsi_threshold"]
            ):
                exit_reason = "RSI_EXIT"
                fill = row["Close"]
            elif (
                not pd.isna(row.get("SMA_exit", np.nan))
                and row["Close"] >= row["SMA_exit"]
            ):
                exit_reason = "MA_EXIT"
                fill = row["Close"]

            if exit_reason:
                pnl = (fill - pos.entry_price) * pos.shares
                cash += fill * pos.shares
                trade_log.append(
                    Trade(
                        t,
                        pos.entry_date,
                        pos.entry_price,
                        pos.shares,
                        date,
                        fill,
                        exit_reason,
                        pnl,
                        (fill / pos.entry_price - 1) * 100,
                    )
                )
                del open_positions[t]
                cash, bank_balance = sweep_cash(cash, bank_balance, cfg)

        equity = cash
        for t, pos in open_positions.items():
            if date in ticker_dfidx[t].index:
                equity += pos.shares * ticker_dfidx[t].loc[date, "Close"]
            else:
                equity += pos.shares * pos.entry_price

        for t, df in universe.items():
            if t in open_positions:
                continue
            if date not in ticker_posidx[t]:
                continue
            row = ticker_dfidx[t].loc[date]
            if pd.isna(row.get("CumRSI2", np.nan)):
                continue
            if not trend_filter_pass(row, cfg):
                continue
            if row["CumRSI2"] >= cfg["entry_cum_rsi_threshold"]:
                continue

            fill_price = row["Close"]
            hard_stop = fill_price * (1 - cfg["hard_stop_pct"])
            risk_amount = equity * cfg["risk_pct_per_trade"]
            risk_per_share = fill_price * cfg["hard_stop_pct"]
            shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
            cost = shares * fill_price
            if shares <= 0 or cost > cash:
                shares = int(cash / fill_price) if fill_price > 0 else 0
                cost = shares * fill_price
            if shares <= 0:
                continue

            cash -= cost
            open_positions[t] = Position(t, date, fill_price, shares, hard_stop)

        equity_curve.append(
            {"Date": date, "Cash": cash, "Bank": bank_balance, "Equity": equity}
        )

    for t, pos in list(open_positions.items()):
        last_close = universe[t]["Close"].iloc[-1]
        pnl = (last_close - pos.entry_price) * pos.shares
        cash += last_close * pos.shares
        trade_log.append(
            Trade(
                t,
                pos.entry_date,
                pos.entry_price,
                pos.shares,
                universe[t]["Date"].iloc[-1],
                last_close,
                "OPEN_AT_END",
                pnl,
                (last_close / pos.entry_price - 1) * 100,
            )
        )
        cash, bank_balance = sweep_cash(cash, bank_balance, cfg)

    return trade_log, cash, bank_balance, pd.DataFrame(equity_curve)


def main(cfg):
    os.makedirs(cfg["output_dir"], exist_ok=True)
    engine = get_db_engine(cfg["db_url"])
    start_date = cfg.get("start_date")
    end_date = cfg.get("end_date")

    for market_label, m_cfg in cfg["markets"].items():
        index_symbol_id = m_cfg["index_symbol_id"]
        benchmark_symbol_id = m_cfg.get("benchmark_symbol_id", index_symbol_id)

        print(f"\n=== Market: {market_label} (index_symbol_id={index_symbol_id}) ===")
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

        for t, df in universe.items():
            universe[t] = compute_connors_indicators(
                df, cfg, index_return_series=index_return_series
            )

        trade_log, final_cash, bank_balance, equity_curve = run_backtest(
            universe, cfg, market_label
        )
        save_trade_log_by_year(trade_log, cfg["output_dir"], market_label)
        equity_curve_path = os.path.join(
            cfg["output_dir"], f"equity_curve_{market_label}.csv"
        )
        equity_curve.to_csv(equity_curve_path, index=False)
        print(f"  wrote {equity_curve_path}")

        stats = compute_summary_stats(
            trade_log, equity_curve, cfg, final_cash, bank_balance
        )
        print_summary_stats(stats, market_label)
        stats_out = {
            k: (None if isinstance(v, float) and v != v else v)
            for k, v in stats.items()
        }
        stats_out["trend_filter_mode"] = cfg.get("trend_filter_mode")
        summary_path = os.path.join(cfg["output_dir"], f"summary_{market_label}.json")
        with open(summary_path, "w") as f:
            json.dump(stats_out, f, indent=2, default=str)
        print(f"  wrote {summary_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="config_connors_db.json")
    args = parser.parse_args()

    cfg = dict(CONNORS_DEFAULT_CONFIG)
    if os.path.exists(args.config):
        with open(args.config) as f:
            cfg.update(json.load(f))
    else:
        print(f"[warn] {args.config} not found, using defaults only.")

    main(cfg)
