import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from app.core.config import settings
from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("elder_impulse_backtest")

sync_db_url = str(settings.DATABASE_URL).replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url)


# -------------------------------------------------------------------------
# Configuration & Enums
# -------------------------------------------------------------------------


class TimeframeMode(str, Enum):
    WEEKLY_DAILY = "WEEKLY_DAILY"  # Higher: Weekly, Lower: Daily
    DAILY_75MIN = "DAILY_75MIN"  # Higher: Daily, Lower: 75-Min


@dataclass
class BacktestConfig:
    market: str = "NSE"
    timeframe_mode: TimeframeMode = TimeframeMode.WEEKLY_DAILY
    start_date: str = "2023-01-01"
    end_date: str = "2026-08-31"
    initial_trading_capital: float = 1_000_000.0
    position_size_pct: float = 0.10
    max_open_positions: int = 10

    # --- Tunable Levers ---
    swing_high_lookback: int = 60
    swing_high_tolerance_pct: float = 0.03
    enable_1to1_breakeven: bool = False
    exit_ema_period: Optional[int] = (
        None  # None enables dynamic regime exits (21 EMA if STRONG, 8 EMA if WEAK)
    )
    volume_factor: float = 1.25
    sequence_window_days: int = 14


@dataclass
class Position:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    capital_invested: float
    initial_stop: float
    current_stop: float
    r_target_1to1: float
    market_at_entry: str
    hit_1to1: bool = False


# -------------------------------------------------------------------------
# Indicators & Aggregation Helpers
# -------------------------------------------------------------------------


def compute_elder_impulse(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates Alexander Elder's Impulse System (13 EMA + MACD Histogram 12, 26, 9)."""
    df["EMA13"] = df["Close"].ewm(span=13, adjust=False).mean()
    df["EMA13_Slope"] = df["EMA13"] - df["EMA13"].shift(1)

    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD_Line"] = ema12 - ema26
    df["Signal_Line"] = df["MACD_Line"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD_Line"] - df["Signal_Line"]
    df["MACD_Hist_Slope"] = df["MACD_Hist"] - df["MACD_Hist"].shift(1)

    is_green = (df["EMA13_Slope"] > 0) & (df["MACD_Hist_Slope"] > 0)
    is_red = (df["EMA13_Slope"] < 0) & (df["MACD_Hist_Slope"] < 0)

    conditions = [is_green, is_red]
    choices = ["GREEN", "RED"]
    df["Impulse_Color"] = np.select(conditions, choices, default="BLUE")
    return df


def resample_daily_to_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Resamples daily bars to Friday-anchored weekly candles with projected moving averages."""
    df = daily_df.copy().sort_values("Date").drop_duplicates(subset=["Date"])
    df = df.set_index("Date")
    weekly = (
        df.resample("W-FRI")
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna()
        .reset_index()
    )
    # Projected weekly moving averages
    weekly["EMA3_W"] = weekly["Close"].ewm(span=3, adjust=False).mean()
    weekly["SMA10_W"] = weekly["Close"].rolling(10).mean()
    weekly["SMA30_W"] = weekly["Close"].rolling(30).mean()
    weekly["SMA40_W"] = weekly["Close"].rolling(40).mean()
    weekly["PrevWeek_High"] = weekly["High"].shift(1)
    return weekly


def resample_15m_to_75m(intraday_df: pd.DataFrame) -> pd.DataFrame:
    """Resamples 15m bars to 5 daily 75m bars anchored at 09:15 AM."""
    df = intraday_df.copy().sort_values("ts").drop_duplicates(subset=["ts"])
    df = df.set_index("ts")

    resampled = (
        df.resample("75min", offset="15min")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna()
        .reset_index()
    )
    resampled.rename(
        columns={
            "ts": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        },
        inplace=True,
    )

    resampled["time_str"] = resampled["Date"].dt.strftime("%H:%M")
    valid_sessions = ["09:15", "10:30", "11:45", "13:00", "14:15"]
    resampled = resampled[resampled["time_str"].isin(valid_sessions)].copy()
    resampled.drop(columns=["time_str"], inplace=True)
    return resampled


def prepare_lower_timeframe_indicators(
    df: pd.DataFrame,
    config: BacktestConfig,
    is_75m: bool = False,
) -> pd.DataFrame:
    """Computes lower-timeframe EMAs, SMAs, volume averages, and Elder Impulse."""
    df = df.copy().sort_values("Date").drop_duplicates(subset=["Date"])
    df["EMA8"] = df["Close"].ewm(span=8, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA150"] = df["Close"].rolling(150).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()

    df["VolSMA20"] = df["Volume"].rolling(20).mean()
    df["SwingHigh"] = df["High"].shift(1).rolling(config.swing_high_lookback).max()

    df = compute_elder_impulse(df)
    return df


# -------------------------------------------------------------------------
# Market Regime Calculation
# -------------------------------------------------------------------------


def load_market_regime(config: BacktestConfig) -> pd.Series:
    """Computes daily Strong vs. Weak regime from Nifty 500 or SPY."""
    benchmark_id = 2 if config.market == "NSE" else 5201
    query = text("""
        SELECT date AS "Date", close AS "Close"
        FROM market_data_all
        WHERE symbol_id = :sid
        ORDER BY date ASC;
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"sid": benchmark_id})

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").set_index("Date")
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA150"] = df["Close"].rolling(150).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()

    is_strong = (
        (df["Close"] > df["SMA50"])
        & (df["SMA50"] > df["SMA150"])
        & (df["SMA150"] > df["SMA200"])
    )
    regime = is_strong.map({True: "STRONG", False: "WEAK"})
    return regime


# -------------------------------------------------------------------------
# Timing Sequence Validator
# -------------------------------------------------------------------------


def check_timing_sequence(sub_df: pd.DataFrame, max_days: int = 14) -> bool:
    """
    Evaluates prior bars within 14 calendar days:
    Requires >= 3 Greens, >= 1 Blue, and >= 1 Red. Order does not matter.
    """
    if sub_df.empty or len(sub_df) < 5:
        return False

    last_dt = (
        sub_df.index[-1]
        if isinstance(sub_df.index, pd.DatetimeIndex)
        else pd.to_datetime(sub_df["Date"].iloc[-1])
    )
    cutoff_date = last_dt - timedelta(days=max_days)

    if isinstance(sub_df.index, pd.DatetimeIndex):
        window = sub_df.loc[cutoff_date:]
    else:
        window = sub_df[sub_df["Date"] >= cutoff_date]

    if window.empty:
        return False

    colors = window["Impulse_Color"].tolist()
    green_count = colors.count("GREEN")
    blue_count = colors.count("BLUE")
    red_count = colors.count("RED")

    return (green_count >= 3) and (blue_count >= 1) and (red_count >= 1)


# -------------------------------------------------------------------------
# Universe Loader
# -------------------------------------------------------------------------


def load_universe_data(
    config: BacktestConfig,
) -> Dict[str, pd.DataFrame]:
    """Loads and formats multi-timeframe indicator feeds per symbol."""
    if config.market == "NSE":
        symbols_query = text("""
            SELECT DISTINCT s.id, s.trading_symbol
            FROM symbols s
            JOIN index_constituents ic ON s.id = ic.stock_symbol_id
            WHERE ic.index_symbol_id = 2
              AND s.is_active = TRUE
            ORDER BY s.trading_symbol;
        """)
        params = {}
    else:
        symbols_query = text("""
            SELECT s.id, s.trading_symbol
            FROM symbols s
            WHERE s.exchange_id = 12 AND s.is_active = TRUE
            ORDER BY s.trading_symbol;
        """)
        params = {}

    with engine.connect() as conn:
        symbols = conn.execute(symbols_query, params).fetchall()

    logger.info(
        f"Processing {len(symbols)} universe constituents for {config.market} "
        f"under {config.timeframe_mode.value}..."
    )

    universe_data: Dict[str, pd.DataFrame] = {}

    for sid, sym in symbols:
        if config.timeframe_mode == TimeframeMode.WEEKLY_DAILY:
            bars_q = text("""
                SELECT date AS "Date", open AS "Open", high AS "High",
                       low AS "Low", close AS "Close", volume AS "Volume"
                FROM market_data_all
                WHERE symbol_id = :sid AND date >= :start AND date <= :end
                ORDER BY date ASC;
            """)
            with engine.connect() as conn:
                daily = pd.read_sql(
                    bars_q,
                    conn,
                    params={
                        "sid": sid,
                        "start": "2021-01-01",
                        "end": config.end_date,
                    },
                )

            if len(daily) < 250:
                continue

            daily["Date"] = pd.to_datetime(daily["Date"])
            weekly = resample_daily_to_weekly(daily)
            daily = prepare_lower_timeframe_indicators(daily, config, is_75m=False)

            # Backward join weekly moving averages and PrevWeek High
            merged = pd.merge_asof(
                daily.sort_values("Date"),
                weekly[
                    [
                        "Date",
                        "EMA3_W",
                        "SMA10_W",
                        "SMA30_W",
                        "SMA40_W",
                        "PrevWeek_High",
                    ]
                ].sort_values("Date"),
                on="Date",
                direction="backward",
            )
            universe_data[sym] = merged.set_index("Date")

        elif config.timeframe_mode == TimeframeMode.DAILY_75MIN:
            daily_q = text("""
                SELECT date AS "Date", open AS "Open", high AS "High",
                       low AS "Low", close AS "Close", volume AS "Volume"
                FROM market_data_all
                WHERE symbol_id = :sid AND date >= :start AND date <= :end
                ORDER BY date ASC;
            """)
            intra_q = text("""
                SELECT ts, open, high, low, close, volume
                FROM market_data_eod_15min
                WHERE symbol_id = :sid AND ts >= :start AND ts <= :end
                ORDER BY ts ASC;
            """)
            with engine.connect() as conn:
                daily_df = pd.read_sql(
                    daily_q,
                    conn,
                    params={
                        "sid": sid,
                        "start": "2022-01-01",
                        "end": config.end_date,
                    },
                )
                intra_df = pd.read_sql(
                    intra_q,
                    conn,
                    params={
                        "sid": sid,
                        "start": config.start_date,
                        "end": config.end_date,
                    },
                )

            if len(daily_df) < 200 or intra_df.empty:
                continue

            daily_df["Date"] = pd.to_datetime(daily_df["Date"])
            weekly_df = resample_daily_to_weekly(daily_df)
            daily_df["EMA8_D"] = daily_df["Close"].ewm(span=8, adjust=False).mean()
            daily_df["EMA21_D"] = daily_df["Close"].ewm(span=21, adjust=False).mean()
            daily_df["SMA50_D"] = daily_df["Close"].rolling(50).mean()
            daily_df["SMA150_D"] = daily_df["Close"].rolling(150).mean()
            daily_df["SMA200_D"] = daily_df["Close"].rolling(200).mean()

            daily_prep = pd.merge_asof(
                daily_df.sort_values("Date"),
                weekly_df[["Date", "PrevWeek_High"]].sort_values("Date"),
                on="Date",
                direction="backward",
            )

            intra_df["ts"] = pd.to_datetime(intra_df["ts"])
            df_75m = resample_15m_to_75m(intra_df)
            if len(df_75m) < 200:
                continue

            df_75m = prepare_lower_timeframe_indicators(df_75m, config, is_75m=True)

            merged_75m = pd.merge_asof(
                df_75m.sort_values("Date"),
                daily_prep[
                    [
                        "Date",
                        "EMA8_D",
                        "EMA21_D",
                        "SMA50_D",
                        "SMA150_D",
                        "SMA200_D",
                        "PrevWeek_High",
                    ]
                ].sort_values("Date"),
                on="Date",
                direction="backward",
            )
            universe_data[sym] = merged_75m.set_index("Date")

    return universe_data


# -------------------------------------------------------------------------
# Simulation Engine
# -------------------------------------------------------------------------


def run_elder_impulse_backtest(config: BacktestConfig) -> pd.DataFrame:
    regime_series = load_market_regime(config)
    universe_data = load_universe_data(config)

    if not universe_data:
        logger.error("No valid historical data loaded. Aborting simulation.")
        return pd.DataFrame()

    all_timestamps = sorted(
        list(
            set.union(
                *[
                    set(df.loc[config.start_date : config.end_date].index)
                    for df in universe_data.values()
                ]
            )
        )
    )

    trading_balance = config.initial_trading_capital
    cash_account = 0.0
    open_positions: List[Position] = []
    closed_trades: List[Dict[str, Any]] = []

    logger.info(
        f"Starting backtest from {config.start_date} to {config.end_date} across "
        f"{len(all_timestamps)} intervals..."
    )

    for current_ts in all_timestamps:
        current_date_anchor = pd.to_datetime(current_ts).floor("D")
        market_regime = regime_series.asof(current_date_anchor)
        if pd.isna(market_regime):
            market_regime = "WEAK"

        # ---------------------------------------------------------
        # Phase A: Manage Exits
        # ---------------------------------------------------------
        surviving_positions: List[Position] = []
        for pos in open_positions:
            df = universe_data.get(pos.symbol)
            if df is None or current_ts not in df.index:
                surviving_positions.append(pos)
                continue

            bar = df.loc[current_ts]
            close_px = float(bar["Close"])
            low_px = float(bar["Low"])
            high_px = float(bar["High"])

            if (
                getattr(config, "enable_1to1_breakeven", False)
                and not pos.hit_1to1
                and high_px >= pos.r_target_1to1
            ):
                pos.hit_1to1 = True
                pos.current_stop = pos.entry_price

            exit_price: Optional[float] = None
            exit_reason = ""
            if low_px <= pos.current_stop:
                exit_price = pos.current_stop
                exit_reason = "STOP_LOSS" if not pos.hit_1to1 else "BREAKEVEN_1TO1"

            # 3. Check Confirmed Bar Close EMA Violation based on Market Health
            if exit_price is None:
                if config.exit_ema_period is not None:
                    # Explicit override if specified
                    ema_col = f"EMA{config.exit_ema_period}"
                    if ema_col in bar and close_px < bar[ema_col]:
                        exit_price = close_px
                        exit_reason = f"{ema_col}_CLOSE_BREAK"
                else:
                    # Dynamic Market Health Exits:
                    # If market regime is STRONG -> Exit on 21 EMA close break
                    # If market regime is WEAK   -> Exit on 8 EMA close break
                    if market_regime == "STRONG":
                        if close_px < bar["EMA21"]:
                            exit_price = close_px
                            exit_reason = "EMA21_CLOSE_BREAK_STRONG"
                    else:  # WEAK market
                        if close_px < bar["EMA8"]:
                            exit_price = close_px
                            exit_reason = "EMA8_CLOSE_BREAK_WEAK"

            if exit_price is not None:
                gross_proceeds = exit_price * pos.shares
                net_pnl = gross_proceeds - pos.capital_invested

                # Return principal to trading float[cite: 3]
                trading_balance += pos.capital_invested
                if net_pnl > 0:
                    cash_account += net_pnl  # Bank gains to cash account[cite: 3]
                else:
                    trading_balance += net_pnl  # Losses reduce trading float[cite: 3]

                closed_trades.append(
                    {
                        "symbol": pos.symbol,
                        "entry_date": pos.entry_date.strftime("%Y-%m-%d %H:%M")
                        if config.timeframe_mode == TimeframeMode.DAILY_75MIN
                        else pos.entry_date.strftime("%Y-%m-%d"),
                        "exit_date": current_ts.strftime("%Y-%m-%d %H:%M")
                        if config.timeframe_mode == TimeframeMode.DAILY_75MIN
                        else current_ts.strftime("%Y-%m-%d"),
                        "entry_price": pos.entry_price,
                        "exit_price": round(exit_price, 2),
                        "shares": pos.shares,
                        "pnl": round(net_pnl, 2),
                        "return_pct": round(
                            (exit_price / pos.entry_price - 1.0) * 100, 2
                        ),
                        "reason": exit_reason,
                        "hit_1to1": pos.hit_1to1,
                        "regime_entry": pos.market_at_entry,
                    }
                )
            else:
                surviving_positions.append(pos)

        open_positions = surviving_positions

        # ---------------------------------------------------------
        # Phase B: Scan for New Entries
        # ---------------------------------------------------------
        for sym, df in universe_data.items():
            total_equity = trading_balance + cash_account
            alloc_per_trade = total_equity * config.position_size_pct

            # Stop new allocations if combined equity is depleted or max positions reached[cite: 3]
            if (
                total_equity < alloc_per_trade
                or len(open_positions) >= config.max_open_positions
            ):
                break
            if any(p.symbol == sym for p in open_positions):
                continue
            if current_ts not in df.index:
                continue

            sub = df.loc[:current_ts]
            if len(sub) < 30:
                continue

            curr = sub.iloc[-1]
            prior_sub = sub.iloc[:-1]

            # 1. Moving Average Alignment Check
            if config.timeframe_mode == TimeframeMode.WEEKLY_DAILY:
                # Price > 8 EMA (daily) > 3 EMA_W > 10 SMA_W > 30 SMA_W > 40 SMA_W
                c1_mas = (
                    curr["Close"] > curr["EMA8"]
                    and curr["EMA8"] > curr["EMA3_W"]
                    and curr["EMA3_W"] > curr["SMA10_W"]
                    and curr["SMA10_W"] > curr["SMA30_W"]
                    and curr["SMA30_W"] > curr["SMA40_W"]
                )
            else:
                # DAILY_75MIN Mode
                c_daily_prereq = (
                    curr["Close"] > curr["EMA8_D"]
                    and curr["EMA8_D"] > curr["EMA21_D"]
                    and curr["EMA21_D"] > curr["SMA50_D"]
                    and curr["SMA50_D"] > curr["SMA150_D"]
                    and curr["SMA150_D"] > curr["SMA200_D"]
                )
                c_75m_stack = (
                    curr["Close"] > curr["EMA8"]
                    and curr["EMA8"] > curr["EMA21"]
                    and curr["EMA21"] > curr["SMA50"]
                    and curr["SMA50"] > curr["SMA150"]
                    and curr["SMA150"] > curr["SMA200"]
                )
                c1_mas = c_daily_prereq and c_75m_stack

            if not c1_mas:
                continue

            # 2. Touch 8 EMA on Entry Bar (Low <= 8 EMA <= High)
            c2_touch = curr["Low"] <= curr["EMA8"] <= curr["High"]
            if not c2_touch:
                continue

            # 3. Elder Impulse Must Be GREEN
            if curr["Impulse_Color"] != "GREEN":
                continue

            # 4. High Volume: >= 1.25x 20-period Volume SMA
            if pd.isna(curr["VolSMA20"]) or curr["Volume"] < (
                config.volume_factor * curr["VolSMA20"]
            ):
                continue

            # 5. Timing Sequence: >=3 Greens, >=1 Blue, >=1 Red within 14 calendar days
            if not check_timing_sequence(
                prior_sub, max_days=config.sequence_window_days
            ):
                continue

            # 6. Structural Price Filters:
            # Must be within 3% below the swing high: [0.97 * SwingHigh, SwingHigh)[cite: 4]
            swing_high = curr["SwingHigh"]
            min_entry_level = swing_high * (
                1.0 - getattr(config, "swing_high_tolerance_pct", 0.03)
            )

            c6_near_swing_high = (curr["Close"] >= min_entry_level) and (
                curr["Close"] < swing_high
            )

            c6_above_pwh = (
                curr["Close"] > curr["PrevWeek_High"]
                if not pd.isna(curr["PrevWeek_High"])
                else True
            )
            if not (c6_near_swing_high and c6_above_pwh):
                continue

            # ---------------------------------------------------------
            # Phase C: Balance Sizing Model & Execution
            # ---------------------------------------------------------
            entry_px = float(curr["Close"])
            initial_stop = float(curr["Low"])
            risk_per_share = entry_px - initial_stop

            if risk_per_share <= 0:
                continue

            shares = int(alloc_per_trade // entry_px)
            if shares <= 0:
                continue

            invested = shares * entry_px

            # Draw primarily from trading balance; bridge any shortfall from cash account[cite: 3]
            if trading_balance >= invested:
                trading_balance -= invested
            else:
                shortfall = invested - trading_balance
                trading_balance = 0.0
                cash_account -= shortfall

            pos = Position(
                symbol=sym,
                entry_date=current_ts,
                entry_price=entry_px,
                shares=shares,
                capital_invested=invested,
                initial_stop=initial_stop,
                current_stop=initial_stop,
                r_target_1to1=round(entry_px + risk_per_share, 2),
                market_at_entry=market_regime,
            )
            open_positions.append(pos)

    # ---------------------------------------------------------
    # Performance Reporting
    # ---------------------------------------------------------
    trades_df = pd.DataFrame(closed_trades)
    total_equity = trading_balance + cash_account

    print("\n==================== ELDER IMPULSE BACKTEST RESULTS ====================")
    print(f"Timeframe Mode:          {config.timeframe_mode.value}")
    print(f"Market Universe:         {config.market}")
    print(f"Test Window:             {config.start_date} to {config.end_date}")
    print("------------------------------------------------------------------------")
    print(f"Initial Trading Balance: ₹{config.initial_trading_capital:,.2f}")
    print(f"Final Trading Balance:   ₹{trading_balance:,.2f}")
    print(f"Protected Cash Account:  ₹{cash_account:,.2f}")
    print(f"Total Combined Equity:   ₹{total_equity:,.2f}")
    print(
        f"Total Net Return:        {((total_equity / config.initial_trading_capital) - 1.0) * 100:.2f}%"
    )
    print(f"Total Trades Closed:     {len(trades_df)}")

    if not trades_df.empty:
        win_trades = trades_df[trades_df["pnl"] > 0]
        loss_trades = trades_df[trades_df["pnl"] < 0]

        win_rate = (len(win_trades) / len(trades_df)) * 100
        avg_win = win_trades["return_pct"].mean() if not win_trades.empty else 0.0
        avg_loss = loss_trades["return_pct"].mean() if not loss_trades.empty else 0.0
        profit_factor = (
            abs(win_trades["pnl"].sum() / loss_trades["pnl"].sum())
            if not loss_trades.empty and loss_trades["pnl"].sum() != 0
            else np.nan
        )

        print(f"Win Rate:                {win_rate:.1f}%")
        print(f"Profit Factor:           {profit_factor:.2f}")
        print(f"Average Winner:          +{avg_win:.2f}%")
        print(f"Average Loser:           {avg_loss:.2f}%")
        print(
            f"Trades Achieved 1:1 BE:  {trades_df['hit_1to1'].sum()} / {len(trades_df)}"
        )
        print(
            "------------------------------------------------------------------------"
        )
        print("Recent Sample Trades:")
        print(
            trades_df[["symbol", "entry_date", "exit_date", "return_pct", "reason"]]
            .tail(10)
            .to_string(index=False)
        )

    return trades_df


if __name__ == "__main__":
    cfg = BacktestConfig(
        market="NSE",
        timeframe_mode=TimeframeMode.WEEKLY_DAILY,
        start_date="2023-01-01",
        end_date="2026-08-31",
        swing_high_lookback=60,
        swing_high_tolerance_pct=0.03,
        enable_1to1_breakeven=False,
        exit_ema_period=None,
    )
    run_elder_impulse_backtest(cfg)
