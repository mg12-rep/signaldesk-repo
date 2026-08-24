import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url)


def fetch_active_holdings(strategy: str = "ALL", broker: str = "ALL"):
    """Fetches holdings with dynamic stop-loss and exit alerts."""
    query = """
        SELECT 
            h.id, h.ticker, h.broker, h.strategy, h.quantity, 
            h.avg_entry_price, h.highest_close, h.trailing_stop,
            e.close AS current_price
        FROM holdings h
        LEFT JOIN symbols s ON UPPER(h.ticker) = UPPER(s.trading_symbol)
        LEFT JOIN LATERAL (
            SELECT close FROM market_data_eod 
            WHERE symbol_id = s.id 
            ORDER BY date DESC LIMIT 1
        ) e ON true
        WHERE 1=1
    """
    params = {}
    if strategy != "ALL":
        query += " AND UPPER(h.strategy) = :strategy"
        params["strategy"] = strategy.upper()
    if broker != "ALL":
        query += " AND UPPER(h.broker) = :broker"
        params["broker"] = broker.upper()

    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)

    if df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        curr_price = (
            row["current_price"]
            if pd.notna(row["current_price"])
            else row["avg_entry_price"]
        )
        pnl_amt = (curr_price - row["avg_entry_price"]) * row["quantity"]
        pnl_pct = ((curr_price - row["avg_entry_price"]) / row["avg_entry_price"]) * 100

        # Exit condition logic
        action = "HOLD"
        reason = "Trend intact"
        if row["trailing_stop"] and curr_price < row["trailing_stop"]:
            action = "SELL"
            reason = "Breached Trailing Stop"

        records.append(
            {
                "id": int(row["id"]),
                "ticker": row["ticker"],
                "broker": row["broker"],
                "strategy": row["strategy"],
                "qty": int(row["quantity"]),
                "entryPrice": float(row["avg_entry_price"]),
                "currentPrice": float(curr_price),
                "highestClose": float(row["highest_close"])
                if pd.notna(row["highest_close"])
                else curr_price,
                "activeStop": float(row["trailing_stop"])
                if pd.notna(row["trailing_stop"])
                else 0.0,
                "pnlAmt": round(pnl_amt, 2),
                "pnlPct": round(pnl_pct, 2),
                "action": action,
                "reason": reason,
            }
        )
    return records
