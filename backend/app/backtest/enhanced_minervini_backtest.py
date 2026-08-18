import argparse
import json
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema
from sqlalchemy import create_engine, text

"""
Minervini-style VCP Swing Trading Backtest Engine
===================================================

Implements a relaxed/practical version of Mark Minervini's Stage-2 VCP
(Volatility Contraction Pattern) strategy, per the specification worked out
with the user:

STRATEGY RULES
--------------
Trend Template (Stage 2 filter, kept strict):
    - Close > SMA50, SMA150, SMA200
    - SMA150 > SMA200, SMA200 trending up over the last ~20 trading days
    - SMA50 > SMA150 > SMA200
    - Close >= 30% above 52-week low
    - Close within 25% of 52-week high
    - Relative Strength rank (proxy, see note below) >= RS_RANK_THRESHOLD

Base / VCP detection (relaxed per user):
    - Base duration >= 15 trading days (~3 weeks)
    - At least 2 contractions (peak->trough legs), where the 2nd leg's
      depth is smaller than the 1st leg's depth (no strict ratio enforced)
    - "Swing high" = the high that started the base (H0)

Entry:
    - Limit buy at swing_high * (1 - ENTRY_DISCOUNT) i.e. 2.5% BELOW the
      swing high (anticipatory entry, filled if price touches that level
      intraday) -- NOT a breakout-confirmation entry.
    - On the entry (fill) day: Trend Template must pass, and that day's
      volume must be >= VOLUME_MULT (1.25x) the average volume observed
      during the base (used as a proxy for the "breakout day volume"
      condition, since entry happens before the literal breakout here).

Exit:
    - HARD STOP: 5% below entry price.
    - TRAILING STOP: 8% below the highest CLOSE since entry, recalculated
      daily.
    - Active stop = max(hard_stop_price, trailing_stop_price) i.e. the
      hard stop protects the trade until the trailing stop (which only
      rises) climbs above it, at which point the trailing stop takes over
      completely, per user's instruction.
    - PROFIT TAKING: sell half the position (rounded down) the first time
      Close >= entry_price * 1.20.
    - Remaining half exits when Close < SMA50.

Position sizing & portfolio rules:
    - Risk 2.5% of CURRENT TOTAL EQUITY (cash + market value of open
      positions) per trade.
    - Risk-per-share is defined by the HARD STOP distance (5%), i.e.
      shares = (equity * 0.025) / (entry_price * 0.05)
    - No cap on concurrent positions other than available cash.
    - Starting capital: configurable (default 10,00,000 INR).
    - CASH SWEEP: after any sale, if cash balance exceeds the starting
      capital, the excess is swept into `bank_balance` and cash is reset
      to the starting capital ceiling. Only the original capital is ever
      recycled into new trades.

IMPORTANT ASSUMPTIONS (documented, please review/adjust):
-----------------------------------------------------------
1. Base/pivot detection uses a local-extrema (fractal) method on CLOSING
   PRICE with a configurable order (default 3, i.e. a 7-day window) to
   find swing highs/lows. This is a practical proxy for visual chart
   pattern recognition, not a literal implementation of Minervini's
   discretionary method.
2. Relative Strength is approximated with an IBD-style weighted-return
   formula (heavier weight on the most recent quarter) computed for every
   stock in the universe on every date, then converted to a cross-
   sectional percentile rank (0-100) *within the universe you supply*.
   This requires no external index file. RS_RANK_THRESHOLD defaults to 70
   (relaxed from Minervini's usual 80-90 since other filters were loosened).
3. A base is invalidated (must reform) if price closes below the base's
   lowest trough before the entry trigger is hit, or if MAX_BASE_AGE
   trading days pass with no entry.
4. "Volume during the base" (for the 1.25x check) = average volume from
   the base's start (H0) to the day before entry.
5. All position sizing / equity calculations use CLOSE prices for
   valuation; entries and stop-outs use intraday High/Low for fill logic.

Run:  python minervini_backtest.py --config config.json
(or edit the CONFIG dict below directly)
"""

"""
Minervini-style VCP Swing Trading Backtest Engine (PostgreSQL / DB-Driven)
========================================================================
Loads index constituents and daily OHLCV series directly from the database
instead of per-ticker CSV directories.

Run:
    python minervini_backtest.py --config config.json
"""


# ----------------------------------------------------------------------
# CONFIG DEFAULTS
# ----------------------------------------------------------------------

DEFAULT_CONFIG = {
    "db_url": "postgresql://postgres:postgres@localhost:5432/signaldesk",
    "markets": {
        # market_label -> {"index_symbol_id": <id>, "benchmark_symbol_id": <id>}
        "SP500": {"index_symbol_id": 559, "benchmark_symbol_id": 559},
        "NASDAQ100": {"index_symbol_id": 2978, "benchmark_symbol_id": 2978},
        "NIFTY500": {"index_symbol_id": 2, "benchmark_symbol_id": 1},
    },
    "output_dir": "output",
    "start_date": None,  # "YYYY-MM-DD" or None
    "end_date": None,  # "YYYY-MM-DD" or None
    "starting_capital": 1_000_000.0,
    # Trend template
    "rs_rank_threshold": 70,
    "min_pct_above_52w_low": 0.30,
    "max_pct_below_52w_high": 0.25,
    # Base / VCP detection
    "pivot_order": 3,
    "min_base_days": 15,
    "min_contractions": 2,
    "max_base_age_days": 90,
    # Entry
    "entry_discount": 0.025,
    "volume_mult": 1.25,
    # Risk / exits
    "risk_pct_per_trade": 0.025,
    "hard_stop_pct": 0.05,
    "trailing_stop_pct": 0.08,
    "profit_targets": [[0.20, 0.5]],
    "post_profit_trailing_stop_pct": None,
    "final_exit_ma": "SMA50",
    "min_avg_volume": 50_000,
    # Market health / regime filter
    "market_health_method": "sma",  # "sma" | "ema" | "ema_confirmed" | "dual"
    "market_health_ema_fast": 8,
    "market_health_ema_slow": 21,
    "market_health_ema_confirm_days": 3,
    "reinvest_fraction": 1.0,
}


# ----------------------------------------------------------------------
# DATABASE DATA LOADERS
# ----------------------------------------------------------------------


def get_db_engine(db_url: str):
    return create_engine(db_url)


def load_universe_from_db(engine, index_symbol_id: int, start_date=None, end_date=None):
    """
    Loads all constituent stock OHLCV bars for a given index_symbol_id.
    Returns: dict[trading_symbol] = DataFrame (Date, Open, High, Low, Close, Volume)
    """
    date_filter = ""
    params = {"index_symbol_id": index_symbol_id}
    if start_date:
        date_filter += " AND b.date >= :start_date"
        params["start_date"] = pd.Timestamp(start_date)
    if end_date:
        date_filter += " AND b.date <= :end_date"
        params["end_date"] = pd.Timestamp(end_date)

    query = text(f"""
        SELECT 
            s.trading_symbol,
            b.date AS "Date",
            b.open AS "Open",
            b.high AS "High",
            b.low AS "Low",
            b.close AS "Close",
            b.volume AS "Volume"
        FROM index_constituents ic
        JOIN symbols s ON ic.stock_symbol_id = s.id
        JOIN market_data_all b ON b.symbol_id = s.id
        WHERE ic.index_symbol_id = :index_symbol_id
        {date_filter}
        ORDER BY s.trading_symbol, b.date ASC
    """)

    with engine.connect() as conn:
        df_all = pd.read_sql(query, conn, params=params)

    if df_all.empty:
        return {}

    df_all["Date"] = pd.to_datetime(df_all["Date"])
    universe = {}
    for ticker, group in df_all.groupby("trading_symbol"):
        df = (
            group.drop(columns=["trading_symbol"])
            .sort_values("Date")
            .drop_duplicates(subset="Date")
            .reset_index(drop=True)
        )
        if len(df) >= 260:  # ~1 year history minimum for technicals
            universe[ticker] = df

    return universe


def load_benchmark_from_db(
    engine, benchmark_symbol_id: int, start_date=None, end_date=None
):
    """Loads benchmark index daily OHLCV series."""
    date_filter = ""
    params = {"benchmark_symbol_id": benchmark_symbol_id}
    if start_date:
        date_filter += " AND date >= :start_date"
        params["start_date"] = pd.Timestamp(start_date)
    if end_date:
        date_filter += " AND date <= :end_date"
        params["end_date"] = pd.Timestamp(end_date)

    query = text(f"""
        SELECT 
            date AS "Date",
            open AS "Open",
            high AS "High",
            low AS "Low",
            close AS "Close",
            volume AS "Volume"
        FROM market_data_all
        WHERE symbol_id = :benchmark_symbol_id
        {date_filter}
        ORDER BY date ASC
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)

    if df.empty:
        return None

    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").drop_duplicates(subset="Date").reset_index(drop=True)


# ----------------------------------------------------------------------
# INDICATORS & PATTERN LOGIC
# ----------------------------------------------------------------------


def compute_index_weighted_return(index_df):
    idx = index_df.set_index("Date")["Close"]
    r63 = idx / idx.shift(63) - 1
    r126 = idx / idx.shift(126) - 1
    r189 = idx / idx.shift(189) - 1
    r252 = idx / idx.shift(252) - 1
    return 2 * r63 + 1 * r126 + 1 * r189 + 1 * r252


def compute_market_health(index_df, cfg=None):
    cfg = cfg or {}
    method = cfg.get("market_health_method", "sma")
    ema_fast_span = cfg.get("market_health_ema_fast", 8)
    ema_slow_span = cfg.get("market_health_ema_slow", 21)
    confirm_days = cfg.get("market_health_ema_confirm_days", 3)

    idx = index_df.set_index("Date")["Close"]
    sma50 = idx.rolling(50).mean()
    sma200 = idx.rolling(200).mean()
    healthy_sma = (idx > sma50) & (sma50 > sma200)

    ema_fast = idx.ewm(span=ema_fast_span, adjust=False).mean()
    ema_slow = idx.ewm(span=ema_slow_span, adjust=False).mean()
    healthy_ema_raw = (idx > ema_fast) & (ema_fast > ema_slow)
    healthy_ema_confirmed = (
        healthy_ema_raw.rolling(confirm_days).min().astype(bool) & healthy_ema_raw
    )

    if method == "sma":
        healthy = healthy_sma
        warmup_mask = sma200.isna()
    elif method == "ema":
        healthy = healthy_ema_raw
        warmup_mask = ema_slow.isna() | healthy_ema_raw.isna()
    elif method == "ema_confirmed":
        healthy = healthy_ema_confirmed
        warmup_mask = ema_slow.isna() | healthy_ema_confirmed.isna()
    elif method == "dual":
        healthy = healthy_sma | healthy_ema_confirmed
        warmup_mask = sma200.isna()
    else:
        raise ValueError(f"Unknown market_health_method: {method!r}")

    healthy = healthy.fillna(False)
    warmup_mask = warmup_mask.fillna(True)
    return healthy.where(~warmup_mask, True)


def compute_indicators(df, index_return_series=None):
    df = df.copy()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA150"] = df["Close"].rolling(150).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["SMA200_slope20"] = df["SMA200"] - df["SMA200"].shift(20)
    df["High52w"] = df["Close"].rolling(252, min_periods=100).max()
    df["Low52w"] = df["Close"].rolling(252, min_periods=100).min()
    df["AvgVol50"] = df["Volume"].rolling(50).mean()

    r63 = df["Close"] / df["Close"].shift(63) - 1
    r126 = df["Close"] / df["Close"].shift(126) - 1
    r189 = df["Close"] / df["Close"].shift(189) - 1
    r252 = df["Close"] / df["Close"].shift(252) - 1
    df["RS_raw"] = 2 * r63 + 1 * r126 + 1 * r189 + 1 * r252

    if index_return_series is not None:
        aligned = index_return_series.reindex(df["Date"]).ffill()
        df["RS_raw"] = df["RS_raw"] - aligned.values

    return df


def add_rs_rank(universe):
    frames = []
    for ticker, df in universe.items():
        s = df.set_index("Date")["RS_raw"]
        s.name = ticker
        frames.append(s)
    if not frames:
        return
    panel = pd.concat(frames, axis=1)
    rank_pct = panel.rank(axis=1, pct=True) * 100
    for ticker, df in universe.items():
        rs_series = rank_pct[ticker].reindex(df["Date"]).values
        df["RS_rank"] = rs_series


def trend_template_pass(row, cfg):
    if any(
        pd.isna(row[c])
        for c in [
            "SMA50",
            "SMA150",
            "SMA200",
            "SMA200_slope20",
            "High52w",
            "Low52w",
            "RS_rank",
        ]
    ):
        return False
    c = row["Close"]
    return bool(
        c > row["SMA50"] > row["SMA150"] > row["SMA200"]
        and row["SMA200_slope20"] > 0
        and c >= row["Low52w"] * (1 + cfg["min_pct_above_52w_low"])
        and c >= row["High52w"] * (1 - cfg["max_pct_below_52w_high"])
        and row["RS_rank"] >= cfg["rs_rank_threshold"]
    )


def find_pivots(df, order):
    close = df["Close"].values
    hi_idx = argrelextrema(close, np.greater_equal, order=order)[0]
    lo_idx = argrelextrema(close, np.less_equal, order=order)[0]
    pivots = [(i, "H", close[i]) for i in hi_idx] + [(i, "L", close[i]) for i in lo_idx]
    pivots.sort(key=lambda x: x[0])

    cleaned = []
    for p in pivots:
        if not cleaned:
            cleaned.append(p)
            continue
        last = cleaned[-1]
        if p[1] == last[1]:
            if p[1] == "H" and p[2] >= last[2]:
                cleaned[-1] = p
            elif p[1] == "L" and p[2] <= last[2]:
                cleaned[-1] = p
        else:
            cleaned.append(p)
    return cleaned


def detect_entry_signals(df, cfg):
    pivots = find_pivots(df, cfg["pivot_order"])
    setups = []
    n = len(pivots)
    for i in range(n - 3):
        p0 = pivots[i]
        if p0[1] != "H":
            continue
        seq = pivots[i : i + 4]
        types = [p[1] for p in seq]
        if types != ["H", "L", "H", "L"]:
            continue
        H0, L1, H1, L2 = seq
        if H1[2] > H0[2]:
            continue
        leg1_depth = (H0[2] - L1[2]) / H0[2] if H0[2] else np.inf
        leg2_depth = (H1[2] - L2[2]) / H1[2] if H1[2] else np.inf
        if leg2_depth >= leg1_depth:
            continue
        base_start_idx = H0[0]
        confirm_idx = L2[0]
        if confirm_idx - base_start_idx < cfg["min_base_days"]:
            continue
        trough_floor = min(L1[2], L2[2])
        setups.append(
            {
                "swing_high_idx": H0[0],
                "swing_high_price": H0[2],
                "base_start_idx": base_start_idx,
                "confirm_idx": confirm_idx,
                "trough_floor": trough_floor,
                "entry_trigger": H0[2] * (1 - cfg["entry_discount"]),
            }
        )
    return setups


# ----------------------------------------------------------------------
# SIMULATION ENGINE
# ----------------------------------------------------------------------


@dataclass
class Position:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    initial_shares: int
    hard_stop: float
    highest_close: float
    targets_hit: set = field(default_factory=set)

    def any_target_hit(self):
        return len(self.targets_hit) > 0

    def trailing_stop(self, cfg):
        pct = (
            cfg["post_profit_trailing_stop_pct"]
            if self.any_target_hit()
            else cfg["trailing_stop_pct"]
        )
        return self.highest_close * (1 - pct)

    def active_stop(self, cfg):
        return max(self.hard_stop, self.trailing_stop(cfg))


@dataclass
class Trade:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    exit_date: pd.Timestamp
    exit_price: float
    exit_reason: str
    pnl: float
    pnl_pct: float


def sweep_cash(cash, bank_balance, cfg):
    cap = cfg["starting_capital"]
    reinvest_frac = cfg.get("reinvest_fraction", 1.0)
    if cash > cap:
        excess = cash - cap
        to_bank = excess * (1 - reinvest_frac)
        bank_balance += to_bank
        cash -= to_bank
    return cash, bank_balance


def run_backtest(
    universe, cfg, market_label="", index_return_series=None, market_health=None
):
    cfg = dict(cfg)
    if cfg.get("post_profit_trailing_stop_pct") is None:
        cfg["post_profit_trailing_stop_pct"] = cfg["trailing_stop_pct"]
    if "profit_targets" not in cfg or not cfg["profit_targets"]:
        cfg["profit_targets"] = [
            [cfg.get("profit_take_pct", 0.20), cfg.get("profit_take_fraction", 0.5)]
        ]

    print(f"[{market_label}] computing indicators & RS ranks...")
    for t, df in universe.items():
        universe[t] = compute_indicators(df, index_return_series=index_return_series)
    add_rs_rank(universe)

    for t in list(universe.keys()):
        avgvol = universe[t]["AvgVol50"].mean()
        if pd.isna(avgvol) or avgvol < cfg["min_avg_volume"]:
            del universe[t]

    print(f"[{market_label}] detecting VCP base setups for {len(universe)} tickers...")
    ticker_setups = {}
    ticker_dfidx = {}
    for t, df in universe.items():
        df = df.set_index("Date")
        ticker_dfidx[t] = df
        raw = universe[t].reset_index(drop=True)
        ticker_setups[t] = detect_entry_signals(raw, cfg)

    all_dates = sorted(set().union(*[set(df.index) for df in ticker_dfidx.values()]))
    cash = cfg["starting_capital"]
    bank_balance = 0.0
    open_positions = {}
    trade_log = []
    equity_curve = []
    setup_pointer = {t: 0 for t in ticker_setups}
    armed_setup = {t: None for t in ticker_setups}
    ticker_posidx = {
        t: {d: i for i, d in enumerate(universe[t]["Date"])} for t in universe
    }

    print(f"[{market_label}] running simulation over {len(all_dates)} trading days...")

    for date in all_dates:
        # Exits
        for t in list(open_positions.keys()):
            if date not in ticker_dfidx[t].index:
                continue
            row = ticker_dfidx[t].loc[date]
            pos = open_positions[t]
            pos.highest_close = max(pos.highest_close, row["Close"])
            stop_price = pos.active_stop(cfg)

            if row["Low"] <= stop_price:
                fill = (
                    min(row["Open"], stop_price)
                    if row["Open"] < stop_price
                    else stop_price
                )
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
                        "STOP",
                        pnl,
                        (fill / pos.entry_price - 1) * 100,
                    )
                )
                del open_positions[t]
                cash, bank_balance = sweep_cash(cash, bank_balance, cfg)
                continue

            for gain_pct, fraction in cfg["profit_targets"]:
                if gain_pct in pos.targets_hit:
                    continue
                target_price = pos.entry_price * (1 + gain_pct)
                if row["High"] < target_price:
                    continue
                sell_shares = int(pos.initial_shares * fraction)
                sell_shares = min(sell_shares, pos.shares)
                if sell_shares <= 0:
                    pos.targets_hit.add(gain_pct)
                    continue
                fill = target_price
                pnl = (fill - pos.entry_price) * sell_shares
                cash += fill * sell_shares
                pos.shares -= sell_shares
                pos.targets_hit.add(gain_pct)
                trade_log.append(
                    Trade(
                        t,
                        pos.entry_date,
                        pos.entry_price,
                        sell_shares,
                        date,
                        fill,
                        f"PROFIT_TARGET_{int(gain_pct * 100)}",
                        pnl,
                        (fill / pos.entry_price - 1) * 100,
                    )
                )
                cash, bank_balance = sweep_cash(cash, bank_balance, cfg)

            if pos.shares <= 0:
                del open_positions[t]
                continue

            exit_ma_col = cfg.get("final_exit_ma", "SMA50")
            ma_val = row.get(exit_ma_col, np.nan)
            if pos.any_target_hit() and not pd.isna(ma_val) and row["Close"] < ma_val:
                fill = row["Close"]
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
                        f"{exit_ma_col}_EXIT",
                        pnl,
                        (fill / pos.entry_price - 1) * 100,
                    )
                )
                del open_positions[t]
                cash, bank_balance = sweep_cash(cash, bank_balance, cfg)
                continue

        # Equity calculation
        equity = cash
        for t, pos in open_positions.items():
            if date in ticker_dfidx[t].index:
                equity += pos.shares * ticker_dfidx[t].loc[date, "Close"]
            else:
                equity += pos.shares * pos.entry_price

        # Entries
        market_ok = (
            True if market_health is None else bool(market_health.get(date, True))
        )
        if market_ok:
            for t, setups in ticker_setups.items():
                if t in open_positions or date not in ticker_posidx[t]:
                    continue
                pos_i = ticker_posidx[t][date]
                df_t = universe[t]
                row = df_t.iloc[pos_i]

                if armed_setup[t] is None:
                    ptr = setup_pointer[t]
                    while ptr < len(setups) and setups[ptr]["confirm_idx"] > pos_i:
                        ptr += 1
                    if ptr < len(setups):
                        candidate = setups[ptr]
                        if candidate["confirm_idx"] <= pos_i:
                            armed_setup[t] = candidate
                            setup_pointer[t] = ptr

                su = armed_setup[t]
                if su is None:
                    continue

                age = pos_i - su["base_start_idx"]
                if (
                    age > cfg["max_base_age_days"]
                    or row["Close"] < su["trough_floor"] * 0.98
                ):
                    armed_setup[t] = None
                    setup_pointer[t] += 1
                    continue

                trigger = su["entry_trigger"]
                if row["Low"] <= trigger <= row["High"]:
                    fill_price = trigger if row["Open"] >= trigger else row["Open"]
                    if not trend_template_pass(row, cfg):
                        armed_setup[t] = None
                        setup_pointer[t] += 1
                        continue

                    base_vol = df_t.iloc[su["base_start_idx"] : pos_i]["Volume"].mean()
                    if (
                        pd.isna(base_vol)
                        or row["Volume"] < cfg["volume_mult"] * base_vol
                    ):
                        continue

                    risk_amount = equity * cfg["risk_pct_per_trade"]
                    risk_per_share = fill_price * cfg["hard_stop_pct"]
                    shares = (
                        int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
                    )
                    cost = shares * fill_price
                    if shares <= 0 or cost > cash:
                        shares = int(cash / fill_price)
                        cost = shares * fill_price
                    if shares <= 0:
                        continue

                    cash -= cost
                    open_positions[t] = Position(
                        ticker=t,
                        entry_date=date,
                        entry_price=fill_price,
                        shares=shares,
                        initial_shares=shares,
                        hard_stop=fill_price * (1 - cfg["hard_stop_pct"]),
                        highest_close=fill_price,
                    )
                    armed_setup[t] = None
                    setup_pointer[t] += 1

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


def compute_summary_stats(trade_log, equity_curve, cfg, final_cash, bank_balance):
    stats = {}
    total_account_value = final_cash + bank_balance
    stats["total_account_value"] = total_account_value
    stats["total_return_pct"] = (
        total_account_value / cfg["starting_capital"] - 1
    ) * 100
    stats["total_trades"] = len(trade_log)

    if not trade_log:
        return stats

    rows = [
        {
            "PnL": t.pnl,
            "PnL_Pct": t.pnl_pct,
            "ExitReason": t.exit_reason,
            "Ticker": t.ticker,
            "EntryDate": t.entry_date,
        }
        for t in trade_log
    ]
    df = pd.DataFrame(rows)
    grp = df.groupby(["Ticker", "EntryDate"])["PnL"].sum()
    stats["num_positions"] = len(grp)
    stats["position_win_rate_pct"] = (grp > 0).mean() * 100
    gross_profit = df.loc[df["PnL"] > 0, "PnL"].sum()
    gross_loss = -df.loc[df["PnL"] < 0, "PnL"].sum()
    stats["profit_factor"] = (
        (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    )
    stats["avg_win"] = (
        df.loc[df["PnL"] > 0, "PnL"].mean() if (df["PnL"] > 0).any() else 0
    )
    stats["avg_loss"] = (
        df.loc[df["PnL"] < 0, "PnL"].mean() if (df["PnL"] < 0).any() else 0
    )

    if not equity_curve.empty:
        ec = equity_curve.copy()
        ec["AccountValue"] = ec["Equity"] + ec["Bank"]
        n_years = (ec["Date"].iloc[-1] - ec["Date"].iloc[0]).days / 365.25
        start_val = cfg["starting_capital"]
        end_val = ec["AccountValue"].iloc[-1]
        stats["cagr_pct"] = (
            ((end_val / start_val) ** (1 / n_years) - 1) * 100
            if n_years > 0 and end_val > 0
            else float("nan")
        )
        running_max = ec["AccountValue"].cummax()
        drawdown = (ec["AccountValue"] - running_max) / running_max
        stats["max_drawdown_pct"] = drawdown.min() * 100
    return stats


def print_summary_stats(stats, market_label):
    print(f"\n[{market_label}] SUMMARY STATS")
    print(f"  Total account value : {stats['total_account_value']:,.2f}")
    print(f"  Total return         : {stats['total_return_pct']:.2f}%")
    print(f"  CAGR                 : {stats.get('cagr_pct', float('nan')):.2f}%")
    print(
        f"  Max drawdown         : {stats.get('max_drawdown_pct', float('nan')):.2f}%"
    )
    print(f"  Total trades (legs)  : {stats['total_trades']}")
    if "num_positions" in stats:
        print(f"  Positions opened     : {stats['num_positions']}")
        print(f"  Position win rate    : {stats['position_win_rate_pct']:.1f}%")
        print(f"  Profit factor        : {stats['profit_factor']:.2f}")


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
        market_health = None
        idx_df = load_benchmark_from_db(
            engine, benchmark_symbol_id, start_date, end_date
        )
        if idx_df is not None and not idx_df.empty:
            index_return_series = compute_index_weighted_return(idx_df)
            market_health = compute_market_health(idx_df, cfg)
            n_healthy = int(market_health.sum())
            print(
                f"  loaded benchmark symbol {benchmark_symbol_id} ({len(idx_df)} rows) -> "
                f"RS + market-health enabled ({n_healthy}/{len(market_health)} days healthy)"
            )

        trade_log, final_cash, bank_balance, equity_curve = run_backtest(
            universe,
            cfg,
            market_label,
            index_return_series=index_return_series,
            market_health=market_health,
        )

        stats = compute_summary_stats(
            trade_log, equity_curve, cfg, final_cash, bank_balance
        )
        print_summary_stats(stats, market_label)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="config.json")
    args = parser.parse_args()

    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(args.config):
        with open(args.config) as f:
            cfg.update(json.load(f))
    main(cfg)
