import os

import pandas as pd
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text

load_dotenv()
sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url)

router = APIRouter()


class BacktestRequest(BaseModel):
    symbol: str
    strategy: str = "MINERVINI"
    stop_loss_pct: float = 7.0
    profit_target_pct: float = 20.0


@router.post("/run")
def run_backtest(req: BacktestRequest):
    sym = req.symbol.upper()
    query = text("""
        SELECT m.date, m.open, m.high, m.low, m.close
        FROM (
            SELECT symbol_id, date, open, high, low, close FROM market_data_history
            UNION ALL
            SELECT symbol_id, date, open, high, low, close FROM market_data_eod
        ) m
        JOIN symbols s ON m.symbol_id = s.id
        WHERE UPPER(s.trading_symbol) = :symbol
        ORDER BY m.date ASC;
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"symbol": sym})

    if df.empty or len(df) < 200:
        raise HTTPException(
            status_code=404, detail=f"Insufficient historical data for {sym}"
        )

    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()

    trades = []
    in_position = False
    entry_price = 0.0
    entry_date = None

    for i in range(200, len(df)):
        row = df.iloc[i]

        # Simple Trend Entry: 50 SMA crosses above 200 SMA & Close > 50 SMA
        if not in_position:
            if row["close"] > row["sma50"] and row["sma50"] > row["sma200"]:
                in_position = True
                entry_price = row["close"]
                entry_date = row["date"]
        else:
            pct_change = ((row["close"] - entry_price) / entry_price) * 100
            hit_stop = pct_change <= -req.stop_loss_pct
            hit_target = pct_change >= req.profit_target_pct
            trend_broken = row["close"] < row["sma50"]

            if hit_stop or hit_target or trend_broken:
                trades.append(
                    {
                        "entryDate": str(entry_date),
                        "exitDate": str(row["date"]),
                        "entryPrice": entry_price,
                        "exitPrice": row["close"],
                        "pnlPct": round(pct_change, 2),
                        "exitReason": "TARGET"
                        if hit_target
                        else ("STOP_LOSS" if hit_stop else "SMA50_BREACH"),
                    }
                )
                in_position = False

    # Compute Summary Stats
    if not trades:
        return {
            "symbol": sym,
            "totalTrades": 0,
            "winRate": 0,
            "netReturnPct": 0,
            "trades": [],
        }

    trades_df = pd.DataFrame(trades)
    winning_trades = trades_df[trades_df["pnlPct"] > 0]
    win_rate = round((len(winning_trades) / len(trades_df)) * 100, 2)
    net_return = round(trades_df["pnlPct"].sum(), 2)

    return {
        "symbol": sym,
        "strategy": req.strategy,
        "totalTrades": len(trades_df),
        "winRate": win_rate,
        "netReturnPct": net_return,
        "trades": trades,
    }
