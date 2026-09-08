"""
Custom BB-Lower-Band + OBV Pullback Swing Strategy - Backtest Engine (DB)
=============================================================================
Same strategy as bb_obv_swing_backtest.py, but reads price history
directly from the same PostgreSQL database used by
enhanced_minervini_backtest.py / enhanced_connors_pullback_backtest.py,
via "db_url" and "markets" in config (instead of "data_dirs" /
"index_files").

Reuses strategy-agnostic infrastructure directly from
app.backtest.enhanced_minervini_backtest: get_db_engine,
load_universe_from_db, load_benchmark_from_db, compute_indicators, Trade,
sweep_cash, save_trade_log_by_year, compute_summary_stats,
print_summary_stats -- so the DB path also automatically inherits the
pattern-based split-detection safety net baked into those loaders.

See bb_obv_swing_backtest.py's module docstring for the full strategy
description and documented assumptions (close-based execution, OBV net-
vs-monotonic mode, max_holding_days default, BB/ATR parameters, etc.) --
unchanged here, only the data source changed.

Run:  python enhanced_bb_obv_swing_backtest.py --config config_bb_obv_db.json
"""

import argparse
import json
import os

import numpy as np
import pandas as pd
from app.backtest.enhanced_minervini_backtest import (
    Trade,
    compute_index_weighted_return,
    compute_indicators,
    compute_summary_stats,
    get_db_engine,
    load_benchmark_from_db,
    load_universe_from_db,
    print_summary_stats,
    save_trade_log_by_year,
    sweep_cash,
)

BB_OBV_DEFAULT_CONFIG = {
    "db_url": "",
    "markets": {},
    "output_dir": "output_bb_obv",
    "start_date": None,
    "end_date": None,
    "starting_capital": 1_000_000.0,
    "reinvest_fraction": 1.0,
    "bb_period": 20,
    "bb_std": 2.0,
    "atr_period": 14,
    "atr_multiplier": 2.0,
    "obv_lookback_days": 5,
    "obv_mode": "net",  # "net" | "strict_monotonic"
    "max_buy_wait_days": 5,  # ~1 week
    "max_holding_days": 15,  # ~3 weeks, backstop time-stop
    "hard_stop_pct": 0.08,
    "risk_pct_per_trade": 0.02,
    "min_avg_volume": 50_000,
}


def compute_bollinger_bands(close, period=20, num_std=2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return lower, mid, upper


def compute_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def compute_obv(close, volume):
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


def compute_strategy_indicators(df, cfg, index_return_series=None):
    df = compute_indicators(
        df, index_return_series=index_return_series
    )  # SMA50/150/200 etc.
    df["BB_lower"], df["BB_mid"], df["BB_upper"] = compute_bollinger_bands(
        df["Close"], cfg["bb_period"], cfg["bb_std"]
    )
    df["ATR"] = compute_atr(df, cfg["atr_period"])
    df["OBV"] = compute_obv(df["Close"], df["Volume"])
    lookback = cfg["obv_lookback_days"]
    if cfg.get("obv_mode", "net") == "strict_monotonic":
        obv_diff = df["OBV"].diff()
        df["OBV_rising"] = (
            obv_diff.rolling(lookback)
            .apply(lambda x: bool(np.all(x > 0)), raw=True)
            .astype(bool)
        )
    else:
        df["OBV_rising"] = df["OBV"] > df["OBV"].shift(lookback)
    return df


def trend_stack_pass(row):
    sma50, sma150, sma200 = (
        row.get("SMA50", np.nan),
        row.get("SMA150", np.nan),
        row.get("SMA200", np.nan),
    )
    if pd.isna(sma50) or pd.isna(sma150) or pd.isna(sma200):
        return False
    return sma50 > sma150 > sma200


class Position:
    __slots__ = [
        "ticker",
        "entry_date",
        "entry_price",
        "shares",
        "hard_stop",
        "highest_close",
        "hold_days",
        "sell_watching",
    ]

    def __init__(self, ticker, entry_date, entry_price, shares, hard_stop):
        self.ticker = ticker
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares
        self.hard_stop = hard_stop
        self.highest_close = entry_price
        self.hold_days = 0
        self.sell_watching = False

    def active_stop(self, cfg, atr):
        if pd.isna(atr):
            return self.hard_stop
        trailing = self.highest_close - cfg["atr_multiplier"] * atr
        return max(self.hard_stop, trailing)


def run_backtest(universe, cfg, market_label=""):
    print(f"[{market_label}] filtering {len(universe)} tickers by liquidity...")
    for t in list(universe.keys()):
        avgvol = universe[t]["Volume"].rolling(50).mean().mean()
        if pd.isna(avgvol) or avgvol < cfg["min_avg_volume"]:
            del universe[t]

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

    watch_start = {t: None for t in universe}

    print(f"[{market_label}] running simulation over {len(all_dates)} trading days...")
    for date in all_dates:
        # ---- 1. exits ----
        for t in list(open_positions.keys()):
            if date not in ticker_dfidx[t].index:
                continue
            row = ticker_dfidx[t].loc[date]
            pos = open_positions[t]
            pos.hold_days += 1
            pos.highest_close = max(pos.highest_close, row["Close"])

            exit_reason, fill = None, None
            active_stop = pos.active_stop(cfg, row.get("ATR", np.nan))

            if row["Low"] <= active_stop:
                exit_reason = "STOP"
                fill = (
                    min(row["Open"], active_stop)
                    if row["Open"] < active_stop
                    else active_stop
                )
            elif pos.hold_days >= cfg["max_holding_days"]:
                exit_reason = "TIME_EXIT"
                fill = row["Close"]
            else:
                if not pos.sell_watching and row["Close"] > row["BB_upper"]:
                    pos.sell_watching = True
                if pos.sell_watching:
                    is_red = row["Close"] < row["Open"]
                    if is_red and row["Close"] < row["BB_upper"]:
                        exit_reason = "SIGNAL_EXIT"
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

        # ---- 2. equity for sizing ----
        equity = cash
        for t, pos in open_positions.items():
            if date in ticker_dfidx[t].index:
                equity += pos.shares * ticker_dfidx[t].loc[date, "Close"]
            else:
                equity += pos.shares * pos.entry_price

        # ---- 3. entries ----
        for t, df in universe.items():
            if t in open_positions:
                continue
            if date not in ticker_posidx[t]:
                continue
            pos_i = ticker_posidx[t][date]
            row = ticker_dfidx[t].loc[date]

            if pd.isna(row.get("BB_lower", np.nan)):
                continue

            if watch_start[t] is None:
                if trend_stack_pass(row) and row["Close"] < row["BB_lower"]:
                    watch_start[t] = pos_i
                continue

            age = pos_i - watch_start[t]
            if age > cfg["max_buy_wait_days"]:
                watch_start[t] = None
                if trend_stack_pass(row) and row["Close"] < row["BB_lower"]:
                    watch_start[t] = pos_i
                continue

            is_green = row["Close"] > row["Open"]
            obv_rising = bool(row.get("OBV_rising", False))
            if is_green and row["Close"] > row["BB_lower"] and obv_rising:
                fill_price = row["Close"]
                hard_stop = fill_price * (1 - cfg["hard_stop_pct"])
                risk_amount = equity * cfg["risk_pct_per_trade"]
                risk_per_share = fill_price * cfg["hard_stop_pct"]
                shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
                cost = shares * fill_price
                if shares <= 0 or cost > cash:
                    shares = int(cash / fill_price) if fill_price > 0 else 0
                    cost = shares * fill_price
                if shares > 0:
                    cash -= cost
                    open_positions[t] = Position(t, date, fill_price, shares, hard_stop)
                watch_start[t] = None

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

        print(f"  computing BB/OBV/ATR indicators for {len(universe)} tickers...")
        for t, df in universe.items():
            universe[t] = compute_strategy_indicators(
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
        summary_path = os.path.join(cfg["output_dir"], f"summary_{market_label}.json")
        with open(summary_path, "w") as f:
            json.dump(stats_out, f, indent=2, default=str)
        print(f"  wrote {summary_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="config_bb_obv_db.json")
    args = parser.parse_args()

    cfg = dict(BB_OBV_DEFAULT_CONFIG)
    if os.path.exists(args.config):
        with open(args.config) as f:
            cfg.update(json.load(f))
    else:
        print(f"[warn] {args.config} not found, using defaults only.")

    main(cfg)
