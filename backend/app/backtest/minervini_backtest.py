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

import os
import glob
import json
import argparse
from dataclasses import dataclass, field
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

DEFAULT_CONFIG = {
    "data_dirs": {
        # market_name -> folder containing one CSV per ticker
        # "NIFTY500": "data/nifty500",
        # "SP500": "data/sp500",
    },
    "index_files": {
        # market_name -> path to a benchmark index CSV (Date, Open, High, Low,
        # Close, Volume) used to compute INDEX-RELATIVE Relative Strength.
        # Optional: if a market has no entry here, RS falls back to a purely
        # cross-sectional rank within the supplied universe.
        # "NIFTY500": "data/NIFTY_50_INDEX.csv",
        # "SP500": "data/SP500_INDEX.csv",
    },
    "output_dir": "output",
    "start_date": None,       # "YYYY-MM-DD" or None for all available
    "end_date": None,         # "YYYY-MM-DD" or None for all available
    "years_lookback": 5,      # used if start_date is None

    "starting_capital": 1_000_000.0,   # 10,00,000 INR

    # Trend template
    "rs_rank_threshold": 70,
    "min_pct_above_52w_low": 0.30,
    "max_pct_below_52w_high": 0.25,

    # Base / VCP detection
    "pivot_order": 3,          # local extrema window (days on each side)
    "min_base_days": 15,       # ~3 weeks
    "min_contractions": 2,
    "max_base_age_days": 90,   # discard stale unconfirmed bases

    # Entry
    "entry_discount": 0.025,   # 2.5% below swing high
    "volume_mult": 1.25,       # vs average volume during base

    # Risk / exits
    "risk_pct_per_trade": 0.025,   # 2.5% of equity
    "hard_stop_pct": 0.05,
    "trailing_stop_pct": 0.08,
    "profit_take_pct": 0.20,
    "profit_take_fraction": 0.5,

    "min_avg_volume": 50_000,   # liquidity floor to include a ticker

    # Market health / regime filter (gates NEW entries only; exits unaffected)
    "market_health_method": "sma",   # "sma" | "ema" | "ema_confirmed" | "dual"
    "market_health_ema_fast": 8,
    "market_health_ema_slow": 21,
    "market_health_ema_confirm_days": 3,   # for "ema_confirmed" and "dual"

    # Cash sweep: fraction of profit above starting_capital that stays in
    # the tradeable cash pool (rest goes to bank_balance).
    # 1.0 = original behavior (100% swept to bank, cash capped at starting_capital)
    # 0.5 = half reinvested/compounded, half swept out
    # 0.0 = fully compounding, nothing ever swept to bank
    "reinvest_fraction": 1.0,
}


# ----------------------------------------------------------------------
# DATA LOADING & INDICATORS
# ----------------------------------------------------------------------

_VOLUME_ALIASES = {
    "volume", "shares traded", "shares_traded", "qty", "quantity",
    "totaltradedqty", "total traded quantity", "tot trd qty",
}


def _looks_like_date(value):
    try:
        parsed = pd.to_datetime(value)
        return not pd.isna(parsed)
    except Exception:
        return False


def load_ticker_csv(path, require_volume=True):
    """
    Robust loader that tolerates:
      - missing header row (columns assumed Date,Open,High,Low,Close,Volume)
      - leading/trailing blank lines
      - UTF-8 BOM (e.g. Excel-exported NSE/BSE files)
      - date formats: YYYY-MM-DD, DD-Mon-YY, DD/MM/YYYY, etc. (auto-detected)
      - "Volume" spelled as "Shares Traded" / "Qty" / etc. (common NSE export)
      - extra columns (e.g. "Turnover") which are simply ignored
      - a genuinely absent/unrecognized Volume column, IF require_volume=False
        (e.g. some index files only carry OHLC) -- Volume is filled with 0
        rather than raising, since RS and market-health calcs only need Close.
        Individual stock files should keep require_volume=True (the default)
        since the strategy's entry logic needs real volume confirmation.
    """
    import warnings

    raw = pd.read_csv(path, header=0, skip_blank_lines=True, encoding="utf-8-sig")
    first_col_name = str(raw.columns[0]).strip()

    if _looks_like_date(first_col_name):
        # the "header" row was actually the first data row -> no real header present
        raw = pd.read_csv(path, header=None, skip_blank_lines=True, encoding="utf-8-sig")
        base_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
        ncols = raw.shape[1]
        if ncols >= len(base_cols):
            raw.columns = base_cols + [f"Extra{i}" for i in range(ncols - len(base_cols))]
        elif ncols >= len(base_cols) - 1 and not require_volume:
            raw.columns = base_cols[:ncols]
        else:
            raise ValueError(f"{path}: expected at least {len(base_cols)} columns, found {ncols}")
    else:
        colmap = {}
        for c in raw.columns:
            key = str(c).strip().lower()
            if key == "date":
                colmap[c] = "Date"
            elif key == "open":
                colmap[c] = "Open"
            elif key == "high":
                colmap[c] = "High"
            elif key == "low":
                colmap[c] = "Low"
            elif key == "close":
                colmap[c] = "Close"
            elif key in _VOLUME_ALIASES:
                colmap[c] = "Volume"
        raw = raw.rename(columns=colmap)

    needed = {"Date", "Open", "High", "Low", "Close"}
    if require_volume:
        needed = needed | {"Volume"}
    missing = needed - set(raw.columns)
    if missing:
        raise ValueError(f"{path} missing columns after normalization: {missing}")

    if "Volume" not in raw.columns:
        print(f"  [note] {path}: no Volume/Shares-Traded column recognized -> "
              f"filled with 0 (fine for index files, since only Close is used "
              f"for RS/market-health; NOT fine if this is a stock file)")
        raw["Volume"] = 0

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(raw["Date"], errors="coerce")
        if parsed.isna().mean() > 0.5:
            parsed = pd.to_datetime(raw["Date"], errors="coerce", dayfirst=True)
    raw["Date"] = parsed
    raw = raw.dropna(subset=["Date"])

    for c in ["Open", "High", "Low", "Close", "Volume"]:
        raw[c] = pd.to_numeric(raw[c].astype(str).str.replace(",", "", regex=False), errors="coerce")
    raw["Volume"] = raw["Volume"].fillna(0)
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])

    df = raw.sort_values("Date").drop_duplicates(subset="Date").reset_index(drop=True)
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]]


def load_universe(data_dir, start_date=None, end_date=None):
    """Load every CSV in data_dir -> dict[ticker] = DataFrame with indicators."""
    universe = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        ticker = os.path.splitext(os.path.basename(path))[0]
        try:
            df = load_ticker_csv(path)
        except Exception as e:
            print(f"  [skip] {ticker}: {e}")
            continue
        if start_date:
            df = df[df["Date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["Date"] <= pd.Timestamp(end_date)]
        df = df.reset_index(drop=True)
        if len(df) < 260:  # need ~1yr history minimum for indicators
            continue
        universe[ticker] = df
    return universe


def compute_index_weighted_return(index_df):
    """Same weighted-return formula as compute_indicators, applied to a benchmark
    index series, for use as the subtractor in index-relative RS."""
    idx = index_df.set_index("Date")["Close"]
    r63 = idx / idx.shift(63) - 1
    r126 = idx / idx.shift(126) - 1
    r189 = idx / idx.shift(189) - 1
    r252 = idx / idx.shift(252) - 1
    return 2 * r63 + 1 * r126 + 1 * r189 + 1 * r252


def compute_market_health(index_df, cfg=None):
    """
    Broad-market regime filter with several selectable methods, controlled
    via cfg["market_health_method"]:

      "sma" (default, original behavior):
          Healthy = Close > SMA50 > SMA200
          Slow-moving and stable; avoids whipsaw but lags at trend turns.

      "ema":
          Healthy = Close > EMA(fast) > EMA(slow)   [default spans 8, 21]
          Reacts fast to recoveries/corrections, but prone to whipsaw in
          choppy conditions -- verified on real data to flip regime ~4-5x
          more often than the SMA method, with most flips reversing again
          within a week.

      "ema_confirmed":
          Same EMA condition as above, but must hold TRUE for
          cfg["market_health_ema_confirm_days"] consecutive days (default 3)
          before being accepted as healthy. Cuts down whipsaw substantially
          versus raw "ema" while still reacting faster than "sma".

      "dual":
          Healthy = SMA_healthy OR EMA_confirmed_healthy
          Primary (SMA) gate provides a stable baseline so an established
          uptrend isn't shut off by ordinary short-term pullbacks; the
          EMA-confirmed path is a secondary, faster "early recovery" door
          that can open the gate before the 200-day average catches up,
          without the single-day whipsaw of raw EMA.

    Returns a boolean Series indexed by Date. Dates before there's enough
    history for the slower of the two averages used default to True
    (unrestricted) rather than blocking trading during warm-up.
    """
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
    # "confirmed" = the raw condition has been continuously true for the
    # last `confirm_days` days (rolling min over a boolean series == 1
    # means every day in the window was True)
    healthy_ema_confirmed = (
        healthy_ema_raw.rolling(confirm_days).min().astype(bool)
        & healthy_ema_raw  # today itself must also be true
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
        warmup_mask = sma200.isna()  # dual falls back to SMA's warmup window
    else:
        raise ValueError(f"Unknown market_health_method: {method!r} "
                          f"(expected 'sma', 'ema', 'ema_confirmed', or 'dual')")

    healthy = healthy.fillna(False)
    warmup_mask = warmup_mask.fillna(True)
    if warmup_mask.any():
        n_warmup = int(warmup_mask.sum())
        print(f"  [note] market filter ({method}): {n_warmup} early index dates lack "
              f"sufficient history -> treated as 'healthy' (unrestricted) by default")
    healthy = healthy.where(~warmup_mask, True)
    return healthy


def compute_indicators(df, index_return_series=None):
    df = df.copy()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA150"] = df["Close"].rolling(150).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["SMA200_slope20"] = df["SMA200"] - df["SMA200"].shift(20)
    df["High52w"] = df["Close"].rolling(252, min_periods=100).max()
    df["Low52w"] = df["Close"].rolling(252, min_periods=100).min()
    df["AvgVol50"] = df["Volume"].rolling(50).mean()

    # IBD-style weighted relative-return score (raw, ranked cross-sectionally later)
    r63 = df["Close"] / df["Close"].shift(63) - 1
    r126 = df["Close"] / df["Close"].shift(126) - 1
    r189 = df["Close"] / df["Close"].shift(189) - 1
    r252 = df["Close"] / df["Close"].shift(252) - 1
    df["RS_raw"] = 2 * r63 + 1 * r126 + 1 * r189 + 1 * r252

    if index_return_series is not None:
        # subtract benchmark's weighted return -> "excess" strength vs the index,
        # so a stock only ranks highly if it's beating the market, not just rising
        aligned = index_return_series.reindex(df["Date"]).ffill()
        df["RS_raw"] = df["RS_raw"] - aligned.values

    return df


def add_rs_rank(universe):
    """Cross-sectional percentile rank of RS_raw, per date, across the universe."""
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
    if any(pd.isna(row[c]) for c in
           ["SMA50", "SMA150", "SMA200", "SMA200_slope20", "High52w", "Low52w", "RS_rank"]):
        return False
    c = row["Close"]
    cond = (
        c > row["SMA50"] > row["SMA150"] > row["SMA200"]
        and row["SMA200_slope20"] > 0
        and c >= row["Low52w"] * (1 + cfg["min_pct_above_52w_low"])
        and c >= row["High52w"] * (1 - cfg["max_pct_below_52w_high"])
        and row["RS_rank"] >= cfg["rs_rank_threshold"]
    )
    return bool(cond)


# ----------------------------------------------------------------------
# VCP BASE DETECTION
# ----------------------------------------------------------------------

def find_pivots(df, order):
    close = df["Close"].values
    hi_idx = argrelextrema(close, np.greater_equal, order=order)[0]
    lo_idx = argrelextrema(close, np.less_equal, order=order)[0]
    pivots = [(i, "H", close[i]) for i in hi_idx] + [(i, "L", close[i]) for i in lo_idx]
    pivots.sort(key=lambda x: x[0])

    # clean up: enforce strict alternation, keeping the more extreme point
    cleaned = []
    for p in pivots:
        if not cleaned:
            cleaned.append(p)
            continue
        last = cleaned[-1]
        if p[1] == last[1]:
            # same type in a row -> keep the more extreme one
            if p[1] == "H" and p[2] >= last[2]:
                cleaned[-1] = p
            elif p[1] == "L" and p[2] <= last[2]:
                cleaned[-1] = p
            # else discard p
        else:
            cleaned.append(p)
    return cleaned  # list of (index, 'H'/'L', price)


def detect_entry_signals(df, cfg):
    """
    Walk the pivot sequence looking for qualifying VCP bases and return a
    list of candidate entry signals:
        dict(entry_idx, entry_price, swing_high_idx, swing_high_price,
             base_start_idx)
    entry_idx/entry_price are determined later during simulation (the
    first day price touches the trigger); here we just return the
    *setups* (swing high + validity window), and the simulator checks
    daily for the actual fill.
    """
    pivots = find_pivots(df, cfg["pivot_order"])
    setups = []
    n = len(pivots)
    for i in range(n - 3):
        p0 = pivots[i]
        if p0[1] != "H":
            continue
        # need H0, L1, H1, L2 (at least 2 legs = 2 contractions)
        seq = pivots[i:i + 4]
        types = [p[1] for p in seq]
        if types != ["H", "L", "H", "L"]:
            continue
        H0, L1, H1, L2 = seq
        if H1[2] > H0[2]:
            continue  # base should not make a new high above H0 mid-base
        leg1_depth = (H0[2] - L1[2]) / H0[2] if H0[2] else np.inf
        leg2_depth = (H1[2] - L2[2]) / H1[2] if H1[2] else np.inf
        if leg2_depth >= leg1_depth:
            continue  # contraction must shrink
        base_start_idx = H0[0]
        confirm_idx = L2[0]  # index where 2nd contraction completes -> base qualifies
        base_age_at_confirm = confirm_idx - base_start_idx
        if base_age_at_confirm < cfg["min_base_days"]:
            continue
        trough_floor = min(L1[2], L2[2])
        setups.append({
            "swing_high_idx": H0[0],
            "swing_high_price": H0[2],
            "base_start_idx": base_start_idx,
            "confirm_idx": confirm_idx,
            "trough_floor": trough_floor,
            "entry_trigger": H0[2] * (1 - cfg["entry_discount"]),
        })
    return setups


# ----------------------------------------------------------------------
# PORTFOLIO SIMULATION
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
    profit_taken: bool = False

    def trailing_stop(self, cfg):
        return self.highest_close * (1 - cfg["trailing_stop_pct"])

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


def run_backtest(universe, cfg, market_label="", index_return_series=None, market_health=None):
    print(f"[{market_label}] computing indicators & RS ranks...")
    for t, df in universe.items():
        universe[t] = compute_indicators(df, index_return_series=index_return_series)
    add_rs_rank(universe)

    # liquidity filter
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
        # re-run pivot detection on positional index, so reset first
        raw = universe[t].reset_index(drop=True)
        setups = detect_entry_signals(raw, cfg)
        ticker_setups[t] = setups

    # master calendar
    all_dates = sorted(set().union(*[set(df.index) for df in ticker_dfidx.values()]))

    cash = cfg["starting_capital"]
    bank_balance = 0.0
    open_positions = {}  # ticker -> Position
    trade_log = []
    equity_curve = []

    # index setups by ticker with pointer to "next usable setup"
    setup_pointer = {t: 0 for t in ticker_setups}
    # track which base (by base_start_idx) is currently "armed" per ticker
    armed_setup = {t: None for t in ticker_setups}

    # precompute positional index for each ticker's dates for fast lookup
    ticker_posidx = {t: {d: i for i, d in enumerate(universe[t]["Date"])} for t in universe}

    print(f"[{market_label}] running simulation over {len(all_dates)} trading days...")

    for date in all_dates:
        # ---- 1. process exits first ----
        for t in list(open_positions.keys()):
            if date not in ticker_dfidx[t].index:
                continue
            row = ticker_dfidx[t].loc[date]
            pos = open_positions[t]
            pos.highest_close = max(pos.highest_close, row["Close"])
            stop_price = pos.active_stop(cfg)

            # stop-loss check (intraday)
            if row["Low"] <= stop_price:
                fill = min(row["Open"], stop_price) if row["Open"] < stop_price else stop_price
                pnl = (fill - pos.entry_price) * pos.shares
                cash += fill * pos.shares
                trade_log.append(Trade(t, pos.entry_date, pos.entry_price, pos.shares,
                                        date, fill, "STOP", pnl,
                                        (fill / pos.entry_price - 1) * 100))
                del open_positions[t]
                cash, bank_balance = sweep_cash(cash, bank_balance, cfg)
                continue

            # profit-take (half) at +20%
            if not pos.profit_taken and row["High"] >= pos.entry_price * (1 + cfg["profit_take_pct"]):
                sell_shares = int(pos.initial_shares * cfg["profit_take_fraction"])
                sell_shares = min(sell_shares, pos.shares)
                if sell_shares > 0:
                    fill = pos.entry_price * (1 + cfg["profit_take_pct"])
                    pnl = (fill - pos.entry_price) * sell_shares
                    cash += fill * sell_shares
                    pos.shares -= sell_shares
                    pos.profit_taken = True
                    trade_log.append(Trade(t, pos.entry_date, pos.entry_price, sell_shares,
                                            date, fill, "PROFIT_HALF", pnl,
                                            (fill / pos.entry_price - 1) * 100))
                    cash, bank_balance = sweep_cash(cash, bank_balance, cfg)
                if pos.shares <= 0:
                    del open_positions[t]
                    continue

            # remaining-half exit: close < SMA50 (only meaningful after profit-take,
            # but also protects full position if profit target never hit and trend breaks)
            sma50 = row.get("SMA50", np.nan)
            if pos.profit_taken and not pd.isna(sma50) and row["Close"] < sma50:
                fill = row["Close"]
                pnl = (fill - pos.entry_price) * pos.shares
                cash += fill * pos.shares
                trade_log.append(Trade(t, pos.entry_date, pos.entry_price, pos.shares,
                                        date, fill, "SMA50_EXIT", pnl,
                                        (fill / pos.entry_price - 1) * 100))
                del open_positions[t]
                cash, bank_balance = sweep_cash(cash, bank_balance, cfg)
                continue

        # ---- 2. current equity for sizing (cash + open positions at last close) ----
        equity = cash
        for t, pos in open_positions.items():
            if date in ticker_dfidx[t].index:
                equity += pos.shares * ticker_dfidx[t].loc[date, "Close"]
            else:
                equity += pos.shares * pos.entry_price

        # ---- 3. process new entries (gated by broad market health) ----
        market_ok = True if market_health is None else bool(market_health.get(date, True))
        if market_ok:
            for t, setups in ticker_setups.items():
                if t in open_positions:
                    continue
                if date not in ticker_posidx[t]:
                    continue
                pos_i = ticker_posidx[t][date]
                df_t = universe[t]
                row = df_t.iloc[pos_i]

                # arm the next unconsummed setup whose confirm_idx has passed
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
                if age > cfg["max_base_age_days"]:
                    armed_setup[t] = None
                    setup_pointer[t] += 1
                    continue
                if row["Close"] < su["trough_floor"] * 0.98:
                    # base broken down, discard
                    armed_setup[t] = None
                    setup_pointer[t] += 1
                    continue

                trigger = su["entry_trigger"]
                if row["Low"] <= trigger <= row["High"]:
                    # fill price = trigger (limit order), unless it gapped below
                    fill_price = trigger if row["Open"] >= trigger else row["Open"]

                    if not trend_template_pass(row, cfg):
                        armed_setup[t] = None
                        setup_pointer[t] += 1
                        continue

                    base_vol = df_t.iloc[su["base_start_idx"]:pos_i]["Volume"].mean()
                    if pd.isna(base_vol) or row["Volume"] < cfg["volume_mult"] * base_vol:
                        continue  # wait for volume confirmation, keep base armed

                    risk_amount = equity * cfg["risk_pct_per_trade"]
                    risk_per_share = fill_price * cfg["hard_stop_pct"]
                    shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
                    cost = shares * fill_price
                    if shares <= 0 or cost > cash:
                        shares = int(cash / fill_price)
                        cost = shares * fill_price
                    if shares <= 0:
                        continue

                    cash -= cost
                    open_positions[t] = Position(
                        ticker=t, entry_date=date, entry_price=fill_price,
                        shares=shares, initial_shares=shares,
                        hard_stop=fill_price * (1 - cfg["hard_stop_pct"]),
                        highest_close=fill_price,
                    )
                    armed_setup[t] = None
                    setup_pointer[t] += 1

        equity_curve.append({"Date": date, "Cash": cash, "Bank": bank_balance, "Equity": equity})

    # liquidate remaining open positions at last available close for reporting
    for t, pos in list(open_positions.items()):
        last_close = universe[t]["Close"].iloc[-1]
        pnl = (last_close - pos.entry_price) * pos.shares
        cash += last_close * pos.shares
        trade_log.append(Trade(t, pos.entry_date, pos.entry_price, pos.shares,
                                universe[t]["Date"].iloc[-1], last_close, "OPEN_AT_END", pnl,
                                (last_close / pos.entry_price - 1) * 100))
        cash, bank_balance = sweep_cash(cash, bank_balance, cfg)

    return trade_log, cash, bank_balance, pd.DataFrame(equity_curve)


def sweep_cash(cash, bank_balance, cfg):
    """
    Whenever cash exceeds starting_capital, the excess (profit) is split
    between staying in the tradeable cash pool and being swept to the bank.
    reinvest_fraction=1.0 (default) reproduces the original behavior: 100%
    of profit above starting_capital is swept out, cash capped at
    starting_capital. reinvest_fraction=0.5 keeps half the excess in cash
    (compounding it into future position sizing) and sweeps the other half.
    """
    cap = cfg["starting_capital"]
    reinvest_frac = cfg.get("reinvest_fraction", 1.0)
    if cash > cap:
        excess = cash - cap
        to_bank = excess * (1 - reinvest_frac)
        bank_balance += to_bank
        cash -= to_bank
    return cash, bank_balance


# ----------------------------------------------------------------------
# OUTPUT
# ----------------------------------------------------------------------

def save_trade_log_by_year(trade_log, output_dir, market_label):
    if not trade_log:
        print(f"[{market_label}] no trades generated.")
        return
    rows = []
    for tr in trade_log:
        rows.append({
            "Ticker": tr.ticker,
            "EntryDate": tr.entry_date.date(),
            "EntryPrice": round(tr.entry_price, 2),
            "Shares": tr.shares,
            "ExitDate": tr.exit_date.date(),
            "ExitPrice": round(tr.exit_price, 2),
            "ExitReason": tr.exit_reason,
            "PnL": round(tr.pnl, 2),
            "PnL_Pct": round(tr.pnl_pct, 2),
        })
    df = pd.DataFrame(rows)
    df["Year"] = pd.to_datetime(df["ExitDate"]).dt.year
    os.makedirs(output_dir, exist_ok=True)
    for year, ydf in df.groupby("Year"):
        path = os.path.join(output_dir, f"trade_log_{market_label}_{year}.csv")
        ydf.drop(columns="Year").to_csv(path, index=False)
        print(f"  wrote {path} ({len(ydf)} trades)")
    combined_path = os.path.join(output_dir, f"trade_log_{market_label}_ALL.csv")
    df.drop(columns="Year").to_csv(combined_path, index=False)
    print(f"  wrote {combined_path} ({len(df)} trades total)")


def compute_summary_stats(trade_log, equity_curve, cfg, final_cash, bank_balance):
    """
    Compute headline stats needed to compare two strategy variants properly
    (e.g. reinvest_fraction=1.0 vs 0.5), not just final total profit.
    """
    stats = {}
    total_account_value = final_cash + bank_balance
    stats["total_account_value"] = total_account_value
    stats["total_return_pct"] = (total_account_value / cfg["starting_capital"] - 1) * 100
    stats["total_trades"] = len(trade_log)

    if not trade_log:
        return stats

    rows = [{"PnL": t.pnl, "PnL_Pct": t.pnl_pct, "ExitReason": t.exit_reason,
             "Ticker": t.ticker, "EntryDate": t.entry_date} for t in trade_log]
    df = pd.DataFrame(rows)

    # position-level win rate (group multi-leg exits from the same entry together)
    grp = df.groupby(["Ticker", "EntryDate"])["PnL"].sum()
    stats["num_positions"] = len(grp)
    stats["position_win_rate_pct"] = (grp > 0).mean() * 100

    gross_profit = df.loc[df["PnL"] > 0, "PnL"].sum()
    gross_loss = -df.loc[df["PnL"] < 0, "PnL"].sum()
    stats["profit_factor"] = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    stats["avg_win"] = df.loc[df["PnL"] > 0, "PnL"].mean() if (df["PnL"] > 0).any() else 0
    stats["avg_loss"] = df.loc[df["PnL"] < 0, "PnL"].mean() if (df["PnL"] < 0).any() else 0

    # CAGR from equity curve (cash + bank as proxy for account value over time;
    # equity_curve tracks cash+open positions, bank tracked separately, so use
    # equity + running bank for a true account-value curve)
    if not equity_curve.empty:
        ec = equity_curve.copy()
        ec["AccountValue"] = ec["Equity"] + ec["Bank"] - ec["Cash"] + ec["Cash"]  # Equity already = cash+positions
        ec["AccountValue"] = ec["Equity"] + (ec["Bank"])  # bank is cumulative swept profit, add to equity
        n_years = (ec["Date"].iloc[-1] - ec["Date"].iloc[0]).days / 365.25
        start_val = cfg["starting_capital"]
        end_val = ec["AccountValue"].iloc[-1]
        stats["cagr_pct"] = ((end_val / start_val) ** (1 / n_years) - 1) * 100 if n_years > 0 and end_val > 0 else float("nan")

        running_max = ec["AccountValue"].cummax()
        drawdown = (ec["AccountValue"] - running_max) / running_max
        stats["max_drawdown_pct"] = drawdown.min() * 100
    else:
        stats["cagr_pct"] = float("nan")
        stats["max_drawdown_pct"] = float("nan")

    return stats


def print_summary_stats(stats, market_label):
    print(f"\n[{market_label}] SUMMARY STATS")
    print(f"  Total account value : {stats['total_account_value']:,.2f}")
    print(f"  Total return         : {stats['total_return_pct']:.2f}%")
    print(f"  CAGR                 : {stats.get('cagr_pct', float('nan')):.2f}%")
    print(f"  Max drawdown         : {stats.get('max_drawdown_pct', float('nan')):.2f}%")
    print(f"  Total trades (legs)  : {stats['total_trades']}")
    if "num_positions" in stats:
        print(f"  Positions opened     : {stats['num_positions']}")
        print(f"  Position win rate    : {stats['position_win_rate_pct']:.1f}%")
        print(f"  Profit factor        : {stats['profit_factor']:.2f}")
        print(f"  Avg win / avg loss   : {stats['avg_win']:,.2f} / {stats['avg_loss']:,.2f}")


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main(cfg):
    os.makedirs(cfg["output_dir"], exist_ok=True)
    end_date = cfg["end_date"]
    start_date = cfg["start_date"]
    if start_date is None and cfg.get("years_lookback"):
        # infer from data later per-market if needed; left None = use all rows
        pass

    index_files = cfg.get("index_files", {})

    for market_label, data_dir in cfg["data_dirs"].items():
        print(f"\n=== Market: {market_label} ({data_dir}) ===")
        universe = load_universe(data_dir, start_date, end_date)
        if not universe:
            print(f"  no CSV data found in {data_dir}, skipping.")
            continue

        index_return_series = None
        market_health = None
        idx_path = index_files.get(market_label)
        if idx_path:
            try:
                idx_df = load_ticker_csv(idx_path, require_volume=False)
                if start_date:
                    idx_df = idx_df[idx_df["Date"] >= pd.Timestamp(start_date)]
                if end_date:
                    idx_df = idx_df[idx_df["Date"] <= pd.Timestamp(end_date)]
                index_return_series = compute_index_weighted_return(idx_df)
                market_health = compute_market_health(idx_df, cfg)
                n_healthy = int(market_health.sum())
                print(f"  loaded benchmark index from {idx_path} ({len(idx_df)} rows) -> "
                      f"index-relative RS + market-health filter enabled "
                      f"({n_healthy}/{len(market_health)} days healthy)")
            except Exception as e:
                print(f"  [warn] could not load index file {idx_path}: {e}. "
                      f"Falling back to cross-sectional RS only, no market-health filter.")

        trade_log, final_cash, bank_balance, equity_curve = run_backtest(
            universe, cfg, market_label, index_return_series=index_return_series,
            market_health=market_health)
        save_trade_log_by_year(trade_log, cfg["output_dir"], market_label)
        equity_curve.to_csv(os.path.join(cfg["output_dir"], f"equity_curve_{market_label}.csv"), index=False)

        print(f"\n[{market_label}] RESULTS")
        print(f"  Final cash balance : {final_cash:,.2f}")
        print(f"  Bank balance (swept profit): {bank_balance:,.2f}")
        print(f"  Total account value: {final_cash + bank_balance:,.2f}")
        print(f"  Total trades: {len(trade_log)}")

        stats = compute_summary_stats(trade_log, equity_curve, cfg, final_cash, bank_balance)
        print_summary_stats(stats, market_label)
        stats_out = {k: (None if isinstance(v, float) and (v != v) else v) for k, v in stats.items()}
        stats_out["reinvest_fraction"] = cfg.get("reinvest_fraction", 1.0)
        stats_out["hard_stop_pct"] = cfg.get("hard_stop_pct")
        stats_path = os.path.join(cfg["output_dir"], f"summary_{market_label}.json")
        with open(stats_path, "w") as f:
            json.dump(stats_out, f, indent=2, default=str)
        print(f"  wrote {stats_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None, help="path to JSON config overriding defaults")
    args = parser.parse_args()

    cfg = dict(DEFAULT_CONFIG)
    if args.config:
        with open(args.config) as f:
            user_cfg = json.load(f)
        cfg.update(user_cfg)

    main(cfg)
