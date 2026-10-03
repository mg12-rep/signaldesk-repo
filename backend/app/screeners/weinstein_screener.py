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
    max_extension_pct: float = 0.08,
) -> Optional[Dict[str, Any]]:
    """
    Detects Stage 1 -> Stage 2 breakout transition:
    1. Base resistance based on weekly HIGH over past 16+ weeks.
    2. Price breaking out above resistance and above flat/rising 30-week SMA.
    3. Not overextended (>0% and <= 8% above resistance).
    4. Mansfield RS hooking upward / improving.
    """
    if len(df_weekly) < 35:
        return None

    df = df_weekly.copy()
    df["SMA30"] = df["Close"].rolling(30).mean()
    df["AvgVol10"] = df["Volume"].rolling(10).mean()

    # Base boundaries using true highs and lows
    df["Base_High"] = df["High"].shift(1).rolling(base_lookback_weeks).max()
    df["Base_Low"] = df["Low"].shift(1).rolling(base_lookback_weeks).min()

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    resistance = curr["Base_High"]
    base_low = curr["Base_Low"]

    if pd.isna(resistance) or pd.isna(curr["SMA30"]):
        return None

    # Condition 1: Breakout above resistance
    breakout_occurred = (curr["Close"] > resistance) or (
        prev["Close"] > prev["Base_High"] and curr["Close"] >= prev["Base_High"] * 0.98
    )
    if not breakout_occurred:
        return None

    # Condition 2: Above 30-week SMA
    if curr["Close"] < curr["SMA30"]:
        return None

    # Condition 3: Not overextended past breakout point
    dist_breakout_pct = (curr["Close"] / resistance) - 1.0
    if not (0.00 <= dist_breakout_pct <= max_extension_pct):
        return None

    # Condition 4: 30-week SMA stabilizing/turning
    sma_4w_ago = df["SMA30"].iloc[-5]
    if pd.isna(sma_4w_ago) or (curr["SMA30"] - sma_4w_ago) / sma_4w_ago < -0.005:
        return None

    # Condition 5: Mansfield RS improving
    mrs_curr = curr.get("MRS", np.nan)
    mrs_prev4 = df["MRS"].iloc[-5] if "MRS" in df.columns else np.nan
    if not pd.isna(mrs_curr) and not pd.isna(mrs_prev4):
        if mrs_curr < mrs_prev4:
            return None

    breakout_price = round(float(resistance), 2)
    ideal_entry = round(float(resistance * 1.0025), 2)
    max_buy_price = round(float(resistance * 1.05), 2)
    pullback_zone = (
        f"{round(float(resistance * 0.99), 2)} - {round(float(resistance * 1.02), 2)}"
    )
    weinstein_stop = round(float(base_low * 0.99), 2)

    return {
        "symbol": symbol,
        "name": name,
        "stage": "STAGE_1_TO_2_BREAKOUT",
        "close": round(float(curr["Close"]), 2),
        "current_price": round(float(curr["Close"]), 2),
        "sma30": round(float(curr["SMA30"]), 2),
        "resistance": breakout_price,
        "breakout_level": breakout_price,
        "ideal_entry": ideal_entry,
        "max_buy_limit": max_buy_price,
        "pullback_buy_zone": pullback_zone,
        "weinstein_stop": weinstein_stop,
        "distance_breakout_pct": round(float(dist_breakout_pct * 100), 2),
        "distance_sma_pct": round(
            float(((curr["Close"] / curr["SMA30"]) - 1.0) * 100), 2
        ),
        "mrs": round(float(mrs_curr), 2) if not pd.isna(mrs_curr) else 0.0,
        "volume": int(curr["Volume"]),
        "avg_volume_10w": int(curr["AvgVol10"]) if not pd.isna(curr["AvgVol10"]) else 0,
    }


def scan_etf_stage2(
    df_weekly: pd.DataFrame,
    symbol: str,
    name: str = "",
    min_base_weeks: int = 20,
) -> Optional[Dict[str, Any]]:
    """
    Detects Stage 2 Continuation Breakouts:
    Evaluates completed breakout above multi-week resistance with rising 30-week SMA and MRS.
    """
    if len(df_weekly) < 35:
        return None

    df = df_weekly.copy()
    df["SMA30"] = df["Close"].rolling(30).mean()
    df["SMA30_slope4"] = df["SMA30"] - df["SMA30"].shift(4)
    df["AvgVol10"] = df["Volume"].rolling(10).mean()

    # 26-week base resistance & support evaluated on weekly High & Low
    df["Resistance26"] = df["High"].shift(2).rolling(min_base_weeks).max()
    df["Swing_Low"] = df["Low"].shift(2).rolling(min_base_weeks).min()

    curr = df.iloc[-1]
    completed = df.iloc[-2]
    pre_breakout = df.iloc[-3]

    if pd.isna(completed["Resistance26"]):
        return None

    # 1. Price holding above 30-week SMA
    c1_above_sma = (
        curr["Close"] > curr["SMA30"] and completed["Close"] > completed["SMA30"]
    )

    # 2. 30-week SMA is trending upward
    c2_sma_rising = curr["SMA30_slope4"] > 0

    # 3. Fresh breakout above 26-week resistance
    c3_breakout = (
        completed["Close"] > completed["Resistance26"]
        and pre_breakout["Close"] <= completed["Resistance26"] * 1.01
    ) or (
        curr["Close"] > completed["Resistance26"]
        and completed["Close"] <= completed["Resistance26"] * 1.01
    )

    # 4. Volume expansion on completed bar
    completed_avg_vol = completed["AvgVol10"]
    c4_volume = (
        completed["Volume"] >= (1.15 * completed_avg_vol)
        if (not pd.isna(completed_avg_vol) and completed_avg_vol > 0)
        else True
    )

    # 5. Mansfield RS is positive and rising relative to SPY
    mrs_curr = curr.get("MRS", np.nan)
    mrs_completed = completed.get("MRS", np.nan)
    c5_mrs = (
        not pd.isna(mrs_curr)
        and mrs_curr > 0.0
        and (pd.isna(mrs_completed) or mrs_curr >= mrs_completed - 0.5)
    )

    if c1_above_sma and c2_sma_rising and c3_breakout and c4_volume and c5_mrs:
        res_val = round(float(completed["Resistance26"]), 2)
        dist_breakout_pct = round(((float(curr["Close"]) / res_val) - 1.0) * 100, 2)
        swing_low_val = (
            float(completed["Swing_Low"])
            if not pd.isna(completed["Swing_Low"])
            else float(curr["SMA30"])
        )

        return {
            "symbol": symbol,
            "name": name,
            "stage": "STAGE_2_CONTINUATION",
            "close": round(float(curr["Close"]), 2),
            "current_price": round(float(curr["Close"]), 2),
            "sma30": round(float(curr["SMA30"]), 2),
            "resistance": res_val,
            "breakout_level": res_val,
            "ideal_entry": round(res_val * 1.0025, 2),
            "max_buy_limit": round(res_val * 1.05, 2),
            "pullback_buy_zone": f"{round(res_val * 0.99, 2)} - {round(res_val * 1.02, 2)}",
            "weinstein_stop": round(swing_low_val * 0.99, 2),
            "distance_breakout_pct": dist_breakout_pct,
            "distance_sma_pct": round(
                float(((curr["Close"] / curr["SMA30"]) - 1.0) * 100), 2
            ),
            "mrs": round(float(mrs_curr), 2),
            "volume": int(completed["Volume"]),
            "avg_volume_10w": int(completed_avg_vol)
            if not pd.isna(completed_avg_vol)
            else 0,
        }

    return None


def run_weinstein_etf_screener(
    ticker_list: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
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

    # Base query for active ETFs
    if ticker_list:
        clean_tickers = tuple(t.upper().strip() for t in ticker_list if t.strip())
        if not clean_tickers:
            return []
        etf_symbols_query = text("""
            SELECT DISTINCT ON (UPPER(trading_symbol)) id, trading_symbol, name
            FROM symbols
            WHERE UPPER(trading_symbol) IN :tickers
              AND is_active = TRUE
              AND id != :spy_id
            ORDER BY UPPER(trading_symbol), id;
        """)
        query_params = {"tickers": clean_tickers, "spy_id": SPY_SYMBOL_ID}
    else:
        etf_symbols_query = text("""
            SELECT DISTINCT ON (UPPER(trading_symbol)) id, trading_symbol, name
            FROM symbols
            WHERE asset_class = 'ETF'
              AND exchange_id IN :exchanges
              AND is_active = TRUE
              AND id != :spy_id
            ORDER BY UPPER(trading_symbol), id;
        """)
        query_params = {"exchanges": US_EXCHANGE_IDS, "spy_id": SPY_SYMBOL_ID}

    with engine.connect() as conn:
        etfs = conn.execute(etf_symbols_query, query_params).fetchall()

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
