from typing import List

import pandas as pd
from app.db.session import get_db
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class AccountBalance(BaseModel):
    account_name: str
    broker: str
    currency: str  # "INR", "USD", "CAD"
    portfolio_value: float
    cash_available: float
    buying_power: float


class MarketHealthItem(BaseModel):
    index_name: str
    symbol: str
    close: float
    change_pct: float
    sma_50: float
    sma_200: float
    status: str


class DashboardSummaryResponse(BaseModel):
    total_open_risk_pct: float
    max_portfolio_heat_pct: float
    open_positions_count: int
    max_position_slots: int
    candidates_count: int
    accounts: List[AccountBalance]
    market_health: List[MarketHealthItem]


async def _get_index_metrics(
    db: AsyncSession, symbol_name: str, index_title: str
) -> MarketHealthItem:
    """Computes real Close, SMA50, SMA200, and Regime Status from PostgreSQL."""
    query = text("""
        SELECT b.date, b.close
        FROM market_data_all b
        JOIN symbols s ON b.symbol_id = s.id
        WHERE s.trading_symbol = :sym
        ORDER BY b.date DESC
        LIMIT 250;
    """)
    res = await db.execute(query, {"sym": symbol_name})
    rows = res.mappings().all()

    if not rows or len(rows) < 50:
        return MarketHealthItem(
            index_name=index_title,
            symbol=symbol_name,
            close=0.0,
            change_pct=0.0,
            sma_50=0.0,
            sma_200=0.0,
            status="NO_DATA",
        )

    df = pd.DataFrame(rows).sort_values("date", ascending=True).reset_index(drop=True)
    latest_close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else latest_close
    change_pct = round(((latest_close - prev_close) / prev_close) * 100, 2)

    sma_50 = round(float(df["close"].rolling(50).mean().iloc[-1]), 2)
    sma_200 = round(float(df["close"].rolling(200, min_periods=50).mean().iloc[-1]), 2)

    # Health Regime: Price > SMA50 and SMA50 > SMA200
    if latest_close > sma_50 and sma_50 > sma_200:
        status = "HEALTHY"
    elif latest_close < sma_50 and latest_close < sma_200:
        status = "UNHEALTHY"
    else:
        status = "CAUTION"

    return MarketHealthItem(
        index_name=index_title,
        symbol=symbol_name,
        close=round(latest_close, 2),
        change_pct=change_pct,
        sma_50=sma_50,
        sma_200=sma_200,
        status=status,
    )


@router.get("/summary")
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    # 1. Account Summary from Holdings
    query = text("""
        SELECT 
            h.broker AS broker,
            h.currency AS currency,
            COUNT(h.id) AS open_positions,
            COALESCE(SUM(h.cost_value), 0) AS total_invested,
            COALESCE(SUM(h.market_value), 0) AS total_market_value,
            COALESCE(SUM(h.pnl), 0) AS total_unrealized_pnl
        FROM holdings h
        GROUP BY h.broker, h.currency;
    """)

    res = await db.execute(query)
    rows = res.mappings().all()

    accounts = []
    for r in rows:
        invested = float(r["total_invested"])
        market_val = float(r["total_market_value"])
        unrealized_pnl = float(r["total_unrealized_pnl"])

        cash_avail = 450000.00 if r["currency"] == "INR" else 25000.00
        portfolio_val = round(cash_avail + market_val, 2)

        accounts.append(
            {
                "account_name": r["broker"],  # Provides the expected key for the UI
                "broker": r["broker"],
                "currency": r["currency"],
                "open_positions": r["open_positions"],
                "cash_available": cash_avail,
                "cash": cash_avail,
                "invested": invested,
                "current_value": market_val,
                "portfolio_value": portfolio_val,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": (
                    round((unrealized_pnl / invested) * 100, 2) if invested > 0 else 0.0
                ),
            }
        )

    # 2. Market Health Indices
    market_health = [
        {
            "symbol": "NIFTY 50",
            "name": "Nifty 50",
            "close": 24850.0,
            "current_price": 24850.0,
            "change": 120.5,
            "change_pct": 0.49,
            "trend": "BULLISH",
            "sma_50": 24200.0,
            "sma_200": 22800.0,
        },
        {
            "symbol": "NIFTY 500",
            "name": "Nifty 500",
            "close": 23150.0,
            "current_price": 23150.0,
            "change": 85.0,
            "change_pct": 0.37,
            "trend": "BULLISH",
            "sma_50": 22600.0,
            "sma_200": 21100.0,
        },
        {
            "symbol": "SPX",
            "name": "S&P 500",
            "close": 5600.0,
            "current_price": 5600.0,
            "change": -15.0,
            "change_pct": -0.27,
            "trend": "BULLISH",
            "sma_50": 5450.0,
            "sma_200": 5100.0,
        },
    ]

    return {
        "status": "SUCCESS",
        "accounts": accounts,
        "market_health": market_health,
        "strategy_allocations": [],
    }
