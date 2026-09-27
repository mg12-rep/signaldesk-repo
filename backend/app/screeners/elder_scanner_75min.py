import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
logger = logging.getLogger("elder_scanner")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url, pool_size=5, max_overflow=5)


# -------------------------------------------------------------------------
# Indicators & Resampling Helpers
# -------------------------------------------------------------------------


def compute_elder_impulse(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates Alexander Elder's Impulse System (13 EMA + MACD Histogram 12, 26, 9)[cite: 1]."""
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
    """Resamples daily bars to Friday-anchored weekly candles with PrevWeek High[cite: 1]."""
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
    weekly["PrevWeek_High"] = weekly["High"].shift(1)
    return weekly


def resample_5m_to_75m(
    intraday_df: pd.DataFrame, tz: str = "Asia/Kolkata"
) -> pd.DataFrame:
    """
    Groups intraday 5m bars into the 5 standard daily 75m bars for NSE (375 min total):
    - Bar 1: 09:15 - 10:30 (15 bars)
    - Bar 2: 10:30 - 11:45 (15 bars)
    - Bar 3: 11:45 - 13:00 (15 bars)
    - Bar 4: 13:00 - 14:15 (15 bars)
    - Bar 5: 14:15 - 15:30 (15 bars)
    """
    df = intraday_df.copy().sort_values("ts").drop_duplicates(subset=["ts"])
    df["Date"] = pd.to_datetime(df["ts"])

    if df["Date"].dt.tz is None:
        df["Date"] = df["Date"].dt.tz_localize("UTC").dt.tz_convert(tz)
    else:
        df["Date"] = df["Date"].dt.tz_convert(tz)

    session_map = {}
    bar_starts = [
        ("09:15", "10:30", "09:15"),
        ("10:30", "11:45", "10:30"),
        ("11:45", "13:00", "11:45"),
        ("13:00", "14:15", "13:00"),
        ("14:15", "15:30", "14:15"),
    ]
    for start_t, end_t, anchor in bar_starts:
        times = pd.date_range(
            f"2026-01-01 {start_t}",
            f"2026-01-01 {end_t}",
            freq="5min",
            inclusive="left",
        )
        for t in times:
            session_map[t.strftime("%H:%M")] = anchor

    df["time_str"] = df["Date"].dt.strftime("%H:%M")
    df["anchor_time"] = df["time_str"].map(session_map)
    df = df.dropna(subset=["anchor_time"]).copy()

    df["bar_agg_dt"] = pd.to_datetime(
        df["Date"].dt.strftime("%Y-%m-%d") + " " + df["anchor_time"]
    ).dt.tz_localize(tz)

    resampled = (
        df.groupby("bar_agg_dt")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index()
    )

    resampled.rename(
        columns={
            "bar_agg_dt": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        },
        inplace=True,
    )
    return resampled.sort_values("Date")


def resample_5m_to_65m(
    intraday_df: pd.DataFrame, tz: str = "America/New_York"
) -> pd.DataFrame:
    """
    Groups intraday 5m bars into the 6 standard daily 65m bars for US Equities (390 min total):
    - Bar 1: 09:30 - 10:35 (13 bars)
    - Bar 2: 10:35 - 11:40 (13 bars)
    - Bar 3: 11:40 - 12:45 (13 bars)
    - Bar 4: 12:45 - 13:50 (13 bars)
    - Bar 5: 13:50 - 14:55 (13 bars)
    - Bar 6: 14:55 - 16:00 (13 bars)
    """
    df = intraday_df.copy().sort_values("ts").drop_duplicates(subset=["ts"])
    df["Date"] = pd.to_datetime(df["ts"])

    if df["Date"].dt.tz is None:
        df["Date"] = df["Date"].dt.tz_localize("UTC").dt.tz_convert(tz)
    else:
        df["Date"] = df["Date"].dt.tz_convert(tz)

    session_map = {}
    bar_starts = [
        ("09:30", "10:35", "09:30"),
        ("10:35", "11:40", "10:35"),
        ("11:40", "12:45", "11:40"),
        ("12:45", "13:50", "12:45"),
        ("13:50", "14:55", "13:50"),
        ("14:55", "16:00", "14:55"),
    ]
    for start_t, end_t, anchor in bar_starts:
        times = pd.date_range(
            f"2026-01-01 {start_t}",
            f"2026-01-01 {end_t}",
            freq="5min",
            inclusive="left",
        )
        for t in times:
            session_map[t.strftime("%H:%M")] = anchor

    df["time_str"] = df["Date"].dt.strftime("%H:%M")
    df["anchor_time"] = df["time_str"].map(session_map)
    df = df.dropna(subset=["anchor_time"]).copy()

    df["bar_agg_dt"] = pd.to_datetime(
        df["Date"].dt.strftime("%Y-%m-%d") + " " + df["anchor_time"]
    ).dt.tz_localize(tz)

    resampled = (
        df.groupby("bar_agg_dt")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index()
    )

    resampled.rename(
        columns={
            "bar_agg_dt": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        },
        inplace=True,
    )
    return resampled.sort_values("Date")


# -------------------------------------------------------------------------
# Market Regime Calculation
# -------------------------------------------------------------------------


def get_current_market_regime(market: str = "NSE") -> str:
    """Checks whether the market benchmark is STRONG or WEAK[cite: 1]."""
    benchmark_id = 2 if market == "NSE" else 5201
    query = text("""
        SELECT date AS "Date", close AS "Close"
        FROM market_data_all
        WHERE symbol_id = :sid
        ORDER BY date ASC;
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"sid": benchmark_id})

    if len(df) < 200:
        return "WEAK"

    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA150"] = df["Close"].rolling(150).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    last = df.iloc[-1]

    is_strong = (
        (last["Close"] > last["SMA50"])
        and (last["SMA50"] > last["SMA150"])
        and (last["SMA150"] > last["SMA200"])
    )
    return "STRONG" if is_strong else "WEAK"


# -------------------------------------------------------------------------
# Core Scanner Engine
# -------------------------------------------------------------------------


def scan_elder_impulse(
    market: str = "NSE",
    csv_path: Optional[str] = None,
    swing_high_lookback: int = 20,
    volume_factor: float = 1.0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Scans stocks and returns setup candidates based on pure cascading moving average trends:
    1. Daily: Close > EMA8_D > EMA21_D > SMA50_D > SMA150_D > SMA200_D
    2. Intraday (75m for NSE, 65m for US): SMA50 > SMA150 > SMA200
    """
    market_upper = market.upper().strip()
    is_us = market_upper == "US"
    tz = "America/New_York" if is_us else "Asia/Kolkata"
    market_regime = get_current_market_regime(market_upper)

    if not csv_path:
        csv_path = (
            "C:/Work/signaldesk/data/elder_input_us_stocks.csv"
            if is_us
            else "C:/Work/signaldesk/data/elder_input_nse_stocks.csv"
        )

    filter_symbols: Optional[List[str]] = None
    file_path = Path(csv_path)
    if file_path.exists():
        df_csv = pd.read_csv(file_path)
        symbol_col = None
        for col in [
            "symbol",
            "trading_symbol",
            "Symbol",
            "TradingSymbol",
            "Ticker",
            "ticker",
        ]:
            if col in df_csv.columns:
                symbol_col = col
                break
        if not symbol_col:
            symbol_col = df_csv.columns[0]
        filter_symbols = (
            df_csv[symbol_col]
            .dropna()
            .astype(str)
            .str.strip()
            .str.upper()
            .unique()
            .tolist()
        )
        logger.info(f"Loaded {len(filter_symbols)} tickers from CSV: {csv_path}")
    else:
        logger.warning(
            f"CSV path {csv_path} not found. Scanning all symbols in 5m table."
        )

    # Query targeting market_data_eod_5min
    if filter_symbols:
        symbols_q = text("""
            SELECT DISTINCT s.id, s.trading_symbol
            FROM symbols s
            JOIN market_data_eod_5min m ON s.id = m.symbol_id
            WHERE s.is_active = TRUE AND UPPER(s.trading_symbol) = ANY(:tickers)
            ORDER BY s.trading_symbol;
        """)
        params = {"tickers": filter_symbols}
    else:
        symbols_q = text("""
            SELECT DISTINCT s.id, s.trading_symbol
            FROM symbols s
            JOIN market_data_eod_5min m ON s.id = m.symbol_id
            WHERE s.is_active = TRUE
            ORDER BY s.trading_symbol;
        """)
        params = {}

    with engine.connect() as conn:
        symbols = conn.execute(symbols_q, params).fetchall()

    logger.info(
        f"🔍 Running trend scanner on {len(symbols)} symbols ({market_upper} Regime: {market_regime})..."
    )

    buy_today: List[Dict[str, Any]] = []
    watchlist: List[Dict[str, Any]] = []

    for sid, sym in symbols:
        daily_q = text("""
            SELECT date AS "Date", open AS "Open", high AS "High",
                   low AS "Low", close AS "Close", volume AS "Volume"
            FROM market_data_all
            WHERE symbol_id = :sid
            ORDER BY date ASC;
        """)
        intra_q = text("""
            SELECT ts, open, high, low, close, volume
            FROM market_data_eod_5min
            WHERE symbol_id = :sid
            ORDER BY ts ASC;
        """)

        with engine.connect() as conn:
            daily_df = pd.read_sql(daily_q, conn, params={"sid": sid})
            intra_df = pd.read_sql(intra_q, conn, params={"sid": sid})

        if len(daily_df) < 200 or len(intra_df) < 50:
            continue

        # Prepare Daily anchors
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

        # Dynamic Intraday Resample (65m for US, 75m for NSE)
        if is_us:
            df_intra_resampled = resample_5m_to_65m(intra_df, tz=tz)
        else:
            df_intra_resampled = resample_5m_to_75m(intra_df, tz=tz)

        if len(df_intra_resampled) < 25:
            continue

        df_intra_resampled["EMA8"] = (
            df_intra_resampled["Close"].ewm(span=8, adjust=False).mean()
        )
        df_intra_resampled["EMA21"] = (
            df_intra_resampled["Close"].ewm(span=21, adjust=False).mean()
        )
        df_intra_resampled["SMA50"] = (
            df_intra_resampled["Close"].rolling(50, min_periods=20).mean()
        )
        df_intra_resampled["SMA150"] = (
            df_intra_resampled["Close"].rolling(150, min_periods=50).mean()
        )
        df_intra_resampled["SMA200"] = (
            df_intra_resampled["Close"].rolling(200, min_periods=50).mean()
        )
        df_intra_resampled["VolSMA20"] = df_intra_resampled["Volume"].rolling(20).mean()
        df_intra_resampled["SwingHigh"] = (
            df_intra_resampled["High"].shift(1).rolling(swing_high_lookback).max()
        )
        df_intra_resampled = compute_elder_impulse(df_intra_resampled)

        # Align timestamps for merge_asof
        df_intra_merge = df_intra_resampled.sort_values("Date").copy()
        df_intra_merge["Date"] = pd.to_datetime(
            df_intra_merge["Date"].dt.tz_localize(None)
        ).astype("datetime64[ns]")

        daily_prep_merge = daily_prep.sort_values("Date").copy()
        daily_prep_merge["Date"] = pd.to_datetime(
            daily_prep_merge["Date"].dt.tz_localize(None)
        ).astype("datetime64[ns]")

        merged = pd.merge_asof(
            df_intra_merge,
            daily_prep_merge[
                [
                    "Date",
                    "EMA8_D",
                    "EMA21_D",
                    "SMA50_D",
                    "SMA150_D",
                    "SMA200_D",
                    "PrevWeek_High",
                ]
            ],
            on="Date",
            direction="backward",
        ).set_index("Date")

        curr = merged.iloc[-1]

        # ---------------------------------------------------------
        # 1. Condition 1: Daily Cascading Trend
        # Close > EMA8_D > EMA21_D > SMA50_D > SMA150_D > SMA200_D
        # ---------------------------------------------------------
        c_daily_trend = (
            curr["Close"] > curr["EMA8_D"]
            and curr["EMA8_D"] > curr["EMA21_D"]
            and curr["EMA21_D"] > curr["SMA50_D"]
            and curr["SMA50_D"] > curr["SMA150_D"]
            and curr["SMA150_D"] > curr["SMA200_D"]
        )

        # ---------------------------------------------------------
        # 2. Condition 2: Intraday Cascading Trend (65m or 75m)
        # SMA50 > SMA150 > SMA200
        # ---------------------------------------------------------
        c_intra_trend = (
            not pd.isna(curr["SMA50"])
            and not pd.isna(curr["SMA150"])
            and not pd.isna(curr["SMA200"])
            and (curr["SMA50"] > curr["SMA150"] > curr["SMA200"])
        )

        if not (c_daily_trend and c_intra_trend):
            continue

        entry_price = float(curr["Close"])
        initial_stop = float(curr["Low"])
        risk_per_share = round(max(entry_price - initial_stop, entry_price * 0.015), 2)
        vol_ratio = (
            round(float(curr["Volume"] / curr["VolSMA20"]), 2)
            if not pd.isna(curr["VolSMA20"]) and curr["VolSMA20"] > 0
            else 1.0
        )

        candidate_record = {
            "symbol": sym,
            "signal_timestamp": str(merged.index[-1]),
            "entry_price": round(entry_price, 2),
            "initial_stop": round(initial_stop, 2),
            "risk_per_share": risk_per_share,
            "target_1to1": round(entry_price + risk_per_share, 2),
            "market_regime": market_regime,
            "swing_high": (
                round(float(curr["SwingHigh"]), 2)
                if not pd.isna(curr["SwingHigh"])
                else round(entry_price, 2)
            ),
            "volume_ratio": vol_ratio,
            "color": curr["Impulse_Color"],
        }

        buy_today.append(candidate_record)

    logger.info(
        f"✨ Scanner complete: {len(buy_today)} setup(s) meeting dual cascading criteria."
    )
    return buy_today, watchlist


# Backward compatibility alias
scan_elder_impulse_75min = scan_elder_impulse

if __name__ == "__main__":
    buys, _ = scan_elder_impulse(market="NSE")
    print(f"\n--- QUALIFIED TREND SETUPS ({len(buys)}) ---")
    if buys:
        print(pd.DataFrame(buys).to_string(index=False))
