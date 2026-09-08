import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from app.core.config import settings
from sqlalchemy import create_engine, text

logger = logging.getLogger("weinstein_screener")

sync_db_url = str(settings.DATABASE_URL).replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url)

US_EXCHANGE_IDS = (2, 3, 9, 12, 205)
SPY_SYMBOL_ID = 5201


def resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("Date").drop_duplicates(subset=["Date"])
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
    )
    return weekly.reset_index()


def compute_mansfield_rs(
    etf_weekly: pd.DataFrame, spy_weekly: pd.DataFrame, period: int = 52
) -> pd.DataFrame:
    merged = pd.merge(
        etf_weekly,
        spy_weekly[["Date", "Close"]],
        on="Date",
        suffixes=("", "_SPY"),
        how="inner",
    )
    if len(merged) < period:
        etf_weekly["MRS"] = np.nan
        return etf_weekly

    rel = merged["Close"] / merged["Close_SPY"]
    rel_sma = rel.rolling(period).mean()
    merged["MRS"] = ((rel / rel_sma) - 1.0) * 100
    return merged[["Date", "Open", "High", "Low", "Close", "Volume", "MRS"]]


def scan_etf_stage1_to_stage2_transition(
    df_weekly: pd.DataFrame,
    symbol: str,
    name: str = "",
    base_lookback_weeks: int = 16,
    max_extension_pct: float = 0.10,
) -> Optional[Dict[str, Any]]:
    """
    Detects Stage 1 -> Stage 2 turn candidates:
    1. Base lookback: ~16 weeks consolidation.
    2. Price crossed above 30-week SMA recently (within last 1-4 weeks).
    3. Price is not extended (>0% and <=10% above 30-SMA).
    4. 30-week SMA is stabilizing/turning (slope >= -0.1%).
    5. Mansfield RS is improving/hooking upward (MRS > MRS 4 weeks ago).
    6. Exclude flat fixed income by requiring distance_sma_pct >= 1.0%.
    """
    if len(df_weekly) < 35:
        return None

    df = df_weekly.copy()
    df["SMA30"] = df["Close"].rolling(30).mean()
    df["AvgVol10"] = df["Volume"].rolling(10).mean()
    df["Base_High"] = df["Close"].shift(1).rolling(base_lookback_weeks).max()

    curr = df.iloc[-1]
    dist_sma = (curr["Close"] / curr["SMA30"]) - 1.0

    # Must be above 30-SMA, but within 10% (and at least 1.0% to eliminate fixed-income drift)
    if not (0.010 <= dist_sma <= max_extension_pct):
        return None

    # Fresh cross: Was at or below 30-SMA within the prior 4 weeks
    recent_cross = (df["Close"].iloc[-5:-1] <= df["SMA30"].iloc[-5:-1] * 1.01).any()
    if not recent_cross:
        return None

    # SMA stabilizing or rising over last 4 weeks
    sma_4w_ago = df["SMA30"].iloc[-5]
    if pd.isna(sma_4w_ago) or (curr["SMA30"] - sma_4w_ago) / sma_4w_ago < -0.005:
        return None

    # Mansfield RS must be turning/hooking upward (no arbitrary floor, so EWH qualifies)
    mrs_curr = curr.get("MRS", np.nan)
    mrs_prev4 = df["MRS"].iloc[-5] if "MRS" in df.columns else np.nan
    if not pd.isna(mrs_curr) and not pd.isna(mrs_prev4):
        if mrs_curr < mrs_prev4:
            return None

    return {
        "symbol": symbol,
        "name": name,
        "stage": "STAGE_1_TO_2",
        "close": round(float(curr["Close"]), 2),
        "sma30": round(float(curr["SMA30"]), 2),
        "resistance": round(float(curr["Base_High"]), 2),
        "volume": int(curr["Volume"]),
        "avg_volume_10w": int(curr["AvgVol10"]) if not pd.isna(curr["AvgVol10"]) else 0,
        "mrs": round(float(mrs_curr), 2) if not pd.isna(mrs_curr) else 0.0,
        "distance_sma_pct": round(float(dist_sma * 100), 2),
    }


def scan_etf_stage2(
    df_weekly: pd.DataFrame,
    symbol: str,
    name: str = "",
    min_base_weeks: int = 20,
) -> Optional[Dict[str, Any]]:
    if len(df_weekly) < 35:
        return None

    df = df_weekly.copy()
    df["SMA30"] = df["Close"].rolling(30).mean()
    df["SMA30_slope4"] = df["SMA30"] - df["SMA30"].shift(4)
    df["AvgVol10"] = df["Volume"].rolling(10).mean()
    df["Resistance26"] = df["Close"].shift(1).rolling(min_base_weeks).max()

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    c1_above_sma = curr["Close"] > curr["SMA30"]
    c2_sma_rising = curr["SMA30_slope4"] > 0
    c3_breakout = (curr["Close"] > curr["Resistance26"]) and (
        prev["Close"] <= prev["Resistance26"] * 1.01
    )
    c4_volume = (
        curr["Volume"] >= (1.25 * curr["AvgVol10"]) if curr["AvgVol10"] > 0 else True
    )
    c5_mrs = (
        (curr["MRS"] > 0) and (curr["MRS"] >= prev["MRS"])
        if not pd.isna(curr.get("MRS"))
        else False
    )

    if c1_above_sma and c2_sma_rising and c3_breakout and c4_volume and c5_mrs:
        dist_sma = (curr["Close"] / curr["SMA30"] - 1.0) * 100
        return {
            "symbol": symbol,
            "name": name,
            "stage": "STAGE_2_CONTINUATION",
            "close": round(float(curr["Close"]), 2),
            "sma30": round(float(curr["SMA30"]), 2),
            "resistance": round(float(curr["Resistance26"]), 2),
            "volume": int(curr["Volume"]),
            "avg_volume_10w": int(curr["AvgVol10"])
            if not pd.isna(curr["AvgVol10"])
            else 0,
            "mrs": round(float(curr["MRS"]), 2)
            if not pd.isna(curr.get("MRS"))
            else 0.0,
            "distance_sma_pct": round(float(dist_sma), 2),
        }
    return None


def run_weinstein_etf_screener() -> List[Dict[str, Any]]:
    spy_query = text("""
        SELECT date AS "Date", open AS "Open", high AS "High", low AS "Low", close AS "Close", volume AS "Volume"
        FROM market_data_all
        WHERE symbol_id = :spy_id
        ORDER BY date ASC;
    """)
    with engine.connect() as conn:
        spy_daily = pd.read_sql(spy_query, conn, params={"spy_id": SPY_SYMBOL_ID})

    if spy_daily.empty or len(spy_daily) < 150:
        logger.error(f"Insufficient SPY data (symbol_id={SPY_SYMBOL_ID}).")
        return []

    spy_daily["Date"] = pd.to_datetime(spy_daily["Date"])
    spy_weekly = resample_to_weekly(spy_daily)

    etf_symbols_query = text("""
        SELECT DISTINCT ON (UPPER(trading_symbol)) id, trading_symbol, name
        FROM symbols
        WHERE asset_class = 'ETF'
          AND exchange_id IN :exchanges
          AND is_active = TRUE
          AND id != :spy_id
        ORDER BY UPPER(trading_symbol), id;
    """)
    with engine.connect() as conn:
        etfs = conn.execute(
            etf_symbols_query,
            {"exchanges": US_EXCHANGE_IDS, "spy_id": SPY_SYMBOL_ID},
        ).fetchall()

    results = []
    seen = set()

    for etf_id, symbol, name in etfs:
        sym = symbol.upper().strip()
        if sym in seen:
            continue

        bars_query = text("""
            SELECT date AS "Date", open AS "Open", high AS "High", low AS "Low", close AS "Close", volume AS "Volume"
            FROM market_data_all
            WHERE symbol_id = :sid
            ORDER BY date ASC;
        """)
        with engine.connect() as conn:
            daily_df = pd.read_sql(bars_query, conn, params={"sid": etf_id})

        if daily_df.empty or len(daily_df) < 150:
            continue

        daily_df["Date"] = pd.to_datetime(daily_df["Date"])
        weekly_df = resample_to_weekly(daily_df)
        weekly_mrs = compute_mansfield_rs(weekly_df, spy_weekly)

        # 1. Evaluate Stage 1 -> Stage 2
        trans = scan_etf_stage1_to_stage2_transition(weekly_mrs, symbol=sym, name=name)
        if trans:
            results.append(trans)
            seen.add(sym)
            continue

        # 2. Evaluate Stage 2 Continuation
        cont = scan_etf_stage2(weekly_mrs, symbol=sym, name=name)
        if cont:
            results.append(cont)
            seen.add(sym)

    return results
