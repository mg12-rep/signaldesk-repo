import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url)


def get_market_regime():
    """Computes regime metrics for NIFTY 50 and NIFTY 500."""
    query = text("""
        SELECT s.trading_symbol, m.date, m.close
        FROM market_data_eod m
        JOIN symbols s ON m.symbol_id = s.id
        WHERE s.trading_symbol IN ('NIFTY 50', 'NIFTY 500')
        ORDER BY s.trading_symbol, m.date ASC;
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return {
            "status": "UNKNOWN",
            "nifty50_close": 0,
            "sma50": 0,
            "sma200": 0,
            "regime": "NEUTRAL",
        }

    results = {}
    for sym, group in df.groupby("trading_symbol"):
        group = group.sort_values("date")
        group["sma50"] = group["close"].rolling(window=50).mean()
        group["sma200"] = group["close"].rolling(window=200).mean()
        latest = group.iloc[-1]

        is_bullish = latest["close"] > latest["sma50"] > latest["sma200"]
        results[sym] = {
            "close": float(latest["close"]),
            "sma50": float(latest["sma50"]) if pd.notna(latest["sma50"]) else 0.0,
            "sma200": float(latest["sma200"]) if pd.notna(latest["sma200"]) else 0.0,
            "regime": "BULLISH" if is_bullish else "CAUTION / DEFENSIVE",
        }
    return results
