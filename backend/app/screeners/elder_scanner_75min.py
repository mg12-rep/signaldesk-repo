import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
logger = logging.getLogger("elder_scanner_75min")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url, pool_size=5, max_overflow=5)


# -------------------------------------------------------------------------
# Indicators & Aggregation Helpers
# -------------------------------------------------------------------------


def compute_elder_impulse(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates Alexander Elder's Impulse System (13 EMA + MACD Histogram 12, 26, 9)[cite: 7]."""
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
    """Resamples daily bars to Friday-anchored weekly candles with PrevWeek High[cite: 7]."""
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


def resample_15m_to_75m(
    intraday_df: pd.DataFrame, tz: str = "Asia/Kolkata"
) -> pd.DataFrame:
    """
    Resamples 15m UTC bars into 5 daily 75m bars anchored at 09:15 AM local session[cite: 7].
    """
    df = intraday_df.copy().sort_values("ts").drop_duplicates(subset=["ts"])
    df["Date"] = pd.to_datetime(df["ts"])

    if df["Date"].dt.tz is None:
        df["Date"] = df["Date"].dt.tz_localize("UTC").dt.tz_convert(tz)
    else:
        df["Date"] = df["Date"].dt.tz_convert(tz)

    df = df.set_index("Date")

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


def check_timing_sequence(sub_df: pd.DataFrame, max_days: int = 14) -> bool:
    """
    Requires >= 3 Greens, >= 1 Blue, and >= 1 Red within the prior 14 days[cite: 7].
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
    return (
        (colors.count("GREEN") >= 3)
        and (colors.count("BLUE") >= 1)
        and (colors.count("RED") >= 1)
    )


# -------------------------------------------------------------------------
# Market Regime Calculation
# -------------------------------------------------------------------------


def get_current_market_regime(market: str = "NSE") -> str:
    """Checks whether the market benchmark is STRONG or WEAK[cite: 7]."""
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


def scan_elder_impulse_75min(
    market: str = "NSE",
    csv_path: Optional[str] = "C:/Work/signaldesk/data/elder_input_nse_stocks.csv",
    swing_high_lookback: int = 20,
    swing_high_tolerance_pct: float = 0.03,
    volume_factor: float = 1.25,
) -> List[Dict[str, Any]]:
    """
    Scans stocks present in market_data_eod_15min against the 75-minute setup[cite: 7].
    Filters exclusively by symbols in csv_path if provided.
    """
    tz = "Asia/Kolkata" if market == "NSE" else "America/New_York"
    market_regime = get_current_market_regime(market)

    # 1. Resolve filtered symbols from CSV
    filter_symbols: Optional[List[str]] = None
    if csv_path:
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
                f"CSV path {csv_path} not found. Scanning all symbols in 15m table."
            )

    if filter_symbols:
        symbols_q = text("""
            SELECT DISTINCT s.id, s.trading_symbol
            FROM symbols s
            JOIN market_data_eod_15min m ON s.id = m.symbol_id
            WHERE s.is_active = TRUE AND UPPER(s.trading_symbol) = ANY(:tickers)
            ORDER BY s.trading_symbol;
        """)
        params = {"tickers": filter_symbols}
    else:
        symbols_q = text("""
            SELECT DISTINCT s.id, s.trading_symbol
            FROM symbols s
            JOIN market_data_eod_15min m ON s.id = m.symbol_id
            WHERE s.is_active = TRUE
            ORDER BY s.trading_symbol;
        """)
        params = {}

    with engine.connect() as conn:
        symbols = conn.execute(symbols_q, params).fetchall()

    logger.info(
        f"🔍 Running 75m Elder Impulse Scanner on {len(symbols)} symbols ({market} Regime: {market_regime})..."
    )

    candidates: List[Dict[str, Any]] = []

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
            FROM market_data_eod_15min
            WHERE symbol_id = :sid
            ORDER BY ts ASC;
        """)

        with engine.connect() as conn:
            daily_df = pd.read_sql(daily_q, conn, params={"sid": sid})
            intra_df = pd.read_sql(intra_q, conn, params={"sid": sid})

        if len(daily_df) < 200 or len(intra_df) < 30:
            continue

        # Prepare Daily + Weekly anchors[cite: 7]
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

        # Resample 15m to 75m[cite: 7]
        df_75m = resample_15m_to_75m(intra_df, tz=tz)
        if len(df_75m) < 25:
            continue

        df_75m["EMA8"] = df_75m["Close"].ewm(span=8, adjust=False).mean()
        df_75m["EMA21"] = df_75m["Close"].ewm(span=21, adjust=False).mean()
        df_75m["SMA50"] = df_75m["Close"].rolling(50).mean()
        df_75m["SMA150"] = df_75m["Close"].rolling(150).mean()
        df_75m["SMA200"] = df_75m["Close"].rolling(200).mean()
        df_75m["VolSMA20"] = df_75m["Volume"].rolling(20).mean()
        df_75m["SwingHigh"] = df_75m["High"].shift(1).rolling(swing_high_lookback).max()
        df_75m = compute_elder_impulse(df_75m)

        # Fix timestamp precision and timezone mismatch for merge_asof
        df_75m_merge = df_75m.sort_values("Date").copy()
        df_75m_merge["Date"] = pd.to_datetime(
            df_75m_merge["Date"].dt.tz_localize(None)
        ).astype("datetime64[ns]")

        daily_prep_merge = daily_prep.sort_values("Date").copy()
        daily_prep_merge["Date"] = pd.to_datetime(
            daily_prep_merge["Date"].dt.tz_localize(None)
        ).astype("datetime64[ns]")

        merged = pd.merge_asof(
            df_75m_merge,
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
        prior_sub = merged.iloc[:-1]

        # ---------------------------------------------------------
        # Strategy Rules Verification[cite: 7]
        # ---------------------------------------------------------

        # 1. Multi-timeframe trend alignment stacks[cite: 7]
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
        if not (c_daily_prereq and c_75m_stack):
            continue

        # 2. Bar Touches 8 EMA[cite: 7]
        if not (curr["Low"] <= curr["EMA8"] <= curr["High"]):
            continue

        # 3. Elder Impulse is GREEN[cite: 7]
        if curr["Impulse_Color"] != "GREEN":
            continue

        # 4. Volume >= volume_factor * 20 VolSMA[cite: 7]
        if pd.isna(curr["VolSMA20"]) or curr["Volume"] < (
            volume_factor * curr["VolSMA20"]
        ):
            continue

        # 5. Timing Sequence: >=3 Greens, >=1 Blue, >=1 Red in prior 14 days[cite: 7]
        if not check_timing_sequence(prior_sub, max_days=14):
            continue

        # 6. Breakout Level Proximity & Above PrevWeek High[cite: 7]
        swing_high = curr["SwingHigh"]
        min_entry_level = swing_high * (1.0 - swing_high_tolerance_pct)
        c_near_swing_high = (curr["Close"] >= min_entry_level) and (
            curr["Close"] < swing_high
        )
        c_above_pwh = (
            curr["Close"] > curr["PrevWeek_High"]
            if not pd.isna(curr["PrevWeek_High"])
            else True
        )

        if not (c_near_swing_high and c_above_pwh):
            continue

        # Signal Output Calculation
        entry_price = float(curr["Close"])
        initial_stop = float(curr["Low"])
        risk_per_share = round(entry_price - initial_stop, 2)

        candidates.append(
            {
                "symbol": sym,
                "signal_timestamp": str(merged.index[-1]),
                "entry_price": round(entry_price, 2),
                "initial_stop": round(initial_stop, 2),
                "risk_per_share": risk_per_share,
                "target_1to1": round(entry_price + risk_per_share, 2),
                "market_regime": market_regime,
                "swing_high": round(float(swing_high), 2),
                "volume_ratio": round(float(curr["Volume"] / curr["VolSMA20"]), 2),
            }
        )

    logger.info(f"✨ Scanner found {len(candidates)} buy signal(s).")
    return candidates


if __name__ == "__main__":
    csv_file = "C:/Work/signaldesk/data/elder_input_nse_stocks.csv"
    results = scan_elder_impulse_75min(market="NSE", csv_path=csv_file)
    if results:
        print(pd.DataFrame(results).to_string(index=False))
    else:
        print("No candidates currently triggered.")
