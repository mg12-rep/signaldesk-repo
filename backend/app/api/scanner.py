import os

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import APIRouter, Query
from sqlalchemy import create_engine, text

load_dotenv()
sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url)

router = APIRouter()


def compute_rsi(series: pd.Series, period: int = 2) -> pd.Series:
    """Calculates Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def scan_minervini_stage2() -> list[dict]:
    """
    Minervini Trend Template Criteria:
    1. Close > 50 SMA > 150 SMA > 200 SMA
    2. 200 SMA trending up for >= 20 days
    3. Close >= 25% above 52-week low
    4. Close within 25% of 52-week high
    """
    query = text("""
        SELECT s.trading_symbol AS symbol, m.date, m.open, m.high, m.low, m.close, m.volume
        FROM market_data_eod m
        JOIN symbols s ON m.symbol_id = s.id
        WHERE s.is_index = FALSE
        ORDER BY s.trading_symbol, m.date ASC;
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return []

    signals = []
    for symbol, group in df.groupby("symbol"):
        if len(group) < 200:
            continue

        g = group.copy().sort_values("date")
        g["sma50"] = g["close"].rolling(50).mean()
        g["sma150"] = g["close"].rolling(150).mean()
        g["sma200"] = g["close"].rolling(200).mean()
        g["high_52w"] = g["high"].rolling(252, min_periods=100).max()
        g["low_52w"] = g["low"].rolling(252, min_periods=100).min()
        g["vol_sma20"] = g["volume"].rolling(20).mean()

        latest = g.iloc[-1]
        prev_20 = g.iloc[-20] if len(g) >= 20 else g.iloc[0]

        # Trend Template Validation
        cond1 = latest["close"] > latest["sma50"] > latest["sma150"] > latest["sma200"]
        cond2 = latest["sma200"] > prev_20["sma200"]  # 200 SMA sloping upward
        cond3 = latest["close"] >= (latest["low_52w"] * 1.25)  # >= 25% above 52w low
        cond4 = latest["close"] >= (latest["high_52w"] * 0.75)  # within 25% of 52w high

        if cond1 and cond2 and cond3 and cond4:
            vol_multiplier = (
                round(latest["volume"] / latest["vol_sma20"], 2)
                if latest["vol_sma20"] > 0
                else 1.0
            )
            dist_52w_high = round(
                ((latest["close"] - latest["high_52w"]) / latest["high_52w"]) * 100, 2
            )

            signals.append(
                {
                    "symbol": symbol,
                    "strategy": "MINERVINI",
                    "close": float(latest["close"]),
                    "sma50": round(float(latest["sma50"]), 2),
                    "sma200": round(float(latest["sma200"]), 2),
                    "high52w": round(float(latest["high_52w"]), 2),
                    "dist52wHighPct": dist_52w_high,
                    "volumeRatio": vol_multiplier,
                    "triggerDate": str(latest["date"]),
                    "status": "STAGE_2_READY",
                }
            )

    return sorted(signals, key=lambda x: x["dist52wHighPct"], reverse=True)


def scan_connors_rsi() -> list[dict]:
    """
    Connors Mean Reversion Criteria:
    1. Close > 200 SMA (Long-term uptrend)
    2. Connors/Wilder RSI(2) < 10 (Deeply oversold pullback)
    """
    query = text("""
        SELECT s.trading_symbol AS symbol, m.date, m.close
        FROM market_data_eod m
        JOIN symbols s ON m.symbol_id = s.id
        WHERE s.is_index = FALSE
        ORDER BY s.trading_symbol, m.date ASC;
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return []

    signals = []
    for symbol, group in df.groupby("symbol"):
        if len(group) < 200:
            continue

        g = group.copy().sort_values("date")
        g["sma200"] = g["close"].rolling(200).mean()
        g["rsi2"] = compute_rsi(g["close"], period=2)

        latest = g.iloc[-1]

        if latest["close"] > latest["sma200"] and latest["rsi2"] <= 10.0:
            signals.append(
                {
                    "symbol": symbol,
                    "strategy": "CONNORS_RSI",
                    "close": float(latest["close"]),
                    "sma200": round(float(latest["sma200"]), 2),
                    "rsi2": round(float(latest["rsi2"]), 2),
                    "triggerDate": str(latest["date"]),
                    "action": "BUY_PULLBACK",
                }
            )

    return sorted(signals, key=lambda x: x["rsi2"])


@router.get("/run")
def run_scanner(strategy: str = Query("ALL", description="MINERVINI, CONNORS, or ALL")):
    strat = strategy.upper()
    results = {}
    if strat in ["MINERVINI", "ALL"]:
        results["minervini"] = scan_minervini_stage2()
    if strat in ["CONNORS", "ALL"]:
        results["connors"] = scan_connors_rsi()
    return results
