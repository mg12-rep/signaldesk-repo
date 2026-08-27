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


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    # 1. Query benchmark indices
    nifty = await _get_index_metrics(db, "NIFTY 50", "NIFTY 50")
    if nifty.status == "NO_DATA":
        nifty = await _get_index_metrics(db, "NIFTY50", "NIFTY 50")
    if nifty.status == "NO_DATA":
        nifty = await _get_index_metrics(db, "NIFTY 500", "NIFTY 500")

    sp500 = await _get_index_metrics(db, "SPY", "S&P 500 (SPY)")
    nasdaq = await _get_index_metrics(db, "QQQ", "NASDAQ 100 (QQQ)")

    # 2. Count active positions
    pos_res = await db.execute(
        text("SELECT COUNT(*) FROM positions WHERE status = 'OPEN';")
    )
    open_count = pos_res.scalar() or 0

    # 3. Multi-Account balances by native currency
    # 3. Multi-Account balances by native currency
    accounts = [
        AccountBalance(
            account_name="Zerodha Kite (India)",
            broker="ZERODHA",
            currency="INR",
            portfolio_value=1250000.0,
            cash_available=450000.0,
            buying_power=450000.0,
        ),
        AccountBalance(
            account_name="Upstox (India)",
            broker="UPSTOX",
            currency="INR",
            portfolio_value=750000.0,
            cash_available=250000.0,
            buying_power=250000.0,
        ),
        AccountBalance(
            account_name="Interactive Brokers (Global)",
            broker="IBKR",
            currency="USD",
            portfolio_value=65000.0,
            cash_available=18500.0,
            buying_power=37000.0,
        ),
    ]

    return DashboardSummaryResponse(
        total_open_risk_pct=1.8,
        max_portfolio_heat_pct=6.0,
        open_positions_count=open_count,
        max_position_slots=8,
        candidates_count=0,
        accounts=accounts,
        market_health=[nifty, sp500, nasdaq],
    )
