import io
import logging
from typing import List, Optional

import pandas as pd
from app.db.session import get_db
from app.services.exit_recon_service import run_exit_reconciliation_service
from app.services.sync_service import (
    BROKER_CURRENCY,
    BROKER_REGISTRY,
)
from app.services.sync_service import (
    sync_broker_portfolio as run_broker_sync,
)
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
logger = logging.getLogger("holdings_api")


class HoldingItem(BaseModel):
    id: int
    stock_name: str
    ticker: str
    quantity: int
    avg_buy_price: float
    current_price: float
    cost_value: float
    market_value: float
    pnl: float
    pnl_pct: float
    broker: str
    strategy: str
    currency: str


class BrokerStrategySummary(BaseModel):
    broker: str
    strategy: str
    currency: str
    total_pnl: float
    pnl_pct: float
    cash_available: float
    total_cost_value: float
    total_market_value: float
    holdings: List[HoldingItem]


@router.get("/data", response_model=BrokerStrategySummary)
async def get_holdings_data(
    broker: str = Query("ZERODHA"),
    strategy: str = Query("minervini_vcp"),
    db: AsyncSession = Depends(get_db),
):
    broker_upper = broker.strip().upper()
    currency = BROKER_CURRENCY.get(broker_upper, "INR")

    # 1. Query holdings from database
    query = text("""
        SELECT 
            h.id,
            COALESCE(s.name, s.trading_symbol) AS stock_name,
            s.trading_symbol AS ticker,
            h.quantity,
            h.avg_buy_price,
            COALESCE(eod.close, h.current_price) AS current_price,
            h.broker,
            h.strategy,
            h.currency
        FROM holdings h
        JOIN symbols s ON h.symbol_id = s.id
        LEFT JOIN LATERAL (
            SELECT close 
            FROM market_data_eod m 
            WHERE m.symbol_id = s.id 
            ORDER BY m.date DESC 
            LIMIT 1
        ) eod ON TRUE
        WHERE UPPER(h.broker) = UPPER(:broker)
          AND LOWER(h.strategy) = LOWER(:strategy)
          AND h.quantity > 0
        ORDER BY s.trading_symbol ASC;
    """)

    res = await db.execute(query, {"broker": broker_upper, "strategy": strategy})
    rows = res.mappings().all()

    holdings: List[HoldingItem] = []
    total_cost = 0.0
    total_market = 0.0

    for r in rows:
        qty = int(r["quantity"])
        avg_buy = float(r["avg_buy_price"])
        curr_price = float(r["current_price"])

        cost_val = round(qty * avg_buy, 2)
        market_val = round(qty * curr_price, 2)
        pnl = round(market_val - cost_val, 2)
        pnl_pct = (
            round(((curr_price - avg_buy) / avg_buy) * 100, 2) if avg_buy > 0 else 0.0
        )

        total_cost += cost_val
        total_market += market_val

        holdings.append(
            HoldingItem(
                id=r["id"],
                stock_name=r["stock_name"],
                ticker=r["ticker"],
                quantity=qty,
                avg_buy_price=avg_buy,
                current_price=curr_price,
                cost_value=cost_val,
                market_value=market_val,
                pnl=pnl,
                pnl_pct=pnl_pct,
                broker=r["broker"],
                strategy=r["strategy"],
                currency=currency,
            )
        )

    total_pnl = round(total_market - total_cost, 2)
    overall_pnl_pct = (
        round((total_pnl / total_cost) * 100, 2) if total_cost > 0 else 0.0
    )

    # 2. Query cached cash balance strictly from the DB (Fast & 100% offline)
    cash_res = await db.execute(
        text(
            "SELECT cash_available FROM broker_balances WHERE broker = :broker LIMIT 1;"
        ),
        {"broker": broker_upper},
    )
    cash_row = cash_res.mappings().first()
    cash_available = float(cash_row["cash_available"]) if cash_row else 0.0

    return BrokerStrategySummary(
        broker=broker_upper,
        strategy=strategy,
        currency=currency,
        total_pnl=total_pnl,
        pnl_pct=overall_pnl_pct,
        cash_available=cash_available,
        total_cost_value=round(total_cost, 2),
        total_market_value=round(total_market, 2),
        holdings=holdings,
    )


@router.post("/sync/{broker}")
async def sync_broker_holdings(
    broker: str,
    strategy: str = Query("minervini_vcp"),
    db: AsyncSession = Depends(get_db),
):
    broker_upper = broker.strip().upper()
    try:
        res = await run_broker_sync(
            db=db, broker=broker_upper, default_strategy=strategy
        )
        return {
            "status": "SUCCESS",
            "broker": broker_upper,
            "data": res,
            "message": f"Synced {res['synced_holdings']} holdings and {res['synced_trades']} trades from {broker_upper}.",
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Sync failed for {broker_upper}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Sync failed for {broker_upper}: {str(e)}"
        )


@router.post("/run-exit-recon")
async def run_exit_reconciliation(
    broker: Optional[str] = Query("ZERODHA"),
    strategy: str = Query("minervini_vcp"),
    db: AsyncSession = Depends(get_db),
):
    try:
        recommendations = await run_exit_reconciliation_service(
            db=db,
            broker=broker,
            strategy_label=strategy,
        )
        return {
            "status": "SUCCESS",
            "broker": broker.upper() if broker else "ALL",
            "strategy": strategy,
            "total_evaluated": len(recommendations),
            "recommendations": recommendations,
        }
    except Exception as e:
        logger.error(f"Exit reconciliation failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Exit reconciliation failed: {str(e)}"
        )


@router.post("/upload-csv")
async def upload_holdings_csv(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {e}")

    # Validate required columns
    required_cols = {"ticker", "quantity", "avg_buy_price", "broker", "strategy"}
    df.columns = [c.strip().lower() for c in df.columns]
    if not required_cols.issubset(set(df.columns)):
        missing = required_cols - set(df.columns)
        raise HTTPException(
            status_code=400, detail=f"Missing required columns: {missing}"
        )

    records_imported = 0
    records_failed = []

    for _, row in df.iterrows():
        ticker = str(row["ticker"]).strip().upper()
        qty = int(row["quantity"])
        avg_buy = float(row["avg_buy_price"])
        broker = str(row["broker"]).strip().upper()
        strategy = str(row["strategy"]).strip().lower()
        currency = BROKER_CURRENCY.get(broker, "INR")

        # 1. Resolve Symbol ID from database
        sym_res = await db.execute(
            text(
                "SELECT id FROM symbols WHERE UPPER(trading_symbol) = :sym OR UPPER(trading_symbol) = :sym_eq LIMIT 1;"
            ),
            {"sym": ticker, "sym_eq": f"{ticker}-EQ"},
        )
        sym_row = sym_res.mappings().first()
        if not sym_row:
            records_failed.append(f"{ticker} (Symbol not found in universe)")
            continue

        symbol_id = sym_row["id"]

        # 2. Get latest market close price
        price_res = await db.execute(
            text(
                "SELECT close FROM market_data_eod WHERE symbol_id = :sid ORDER BY date DESC LIMIT 1;"
            ),
            {"sid": symbol_id},
        )
        price_row = price_res.mappings().first()
        current_price = float(price_row["close"]) if price_row else avg_buy

        cost_val = round(qty * avg_buy, 2)
        market_val = round(qty * current_price, 2)
        pnl = round(market_val - cost_val, 2)
        pnl_pct = (
            round(((current_price - avg_buy) / avg_buy) * 100, 2)
            if avg_buy > 0
            else 0.0
        )

        # 3. Upsert Holding
        upsert_query = text("""
            INSERT INTO holdings (
                symbol_id, broker, strategy, currency, quantity, 
                avg_buy_price, current_price, cost_value, market_value, 
                pnl, pnl_pct, entry_date, initial_quantity, updated_at
            )
            VALUES (
                :symbol_id, :broker, :strategy, :currency, :quantity,
                :avg_buy_price, :current_price, :cost_value, :market_value,
                :pnl, :pnl_pct, CURRENT_DATE, :quantity, NOW()
            )
            ON CONFLICT (symbol_id, broker, strategy) DO UPDATE SET
                quantity = EXCLUDED.quantity,
                avg_buy_price = EXCLUDED.avg_buy_price,
                current_price = EXCLUDED.current_price,
                cost_value = EXCLUDED.cost_value,
                market_value = EXCLUDED.market_value,
                pnl = EXCLUDED.pnl,
                pnl_pct = EXCLUDED.pnl_pct,
                updated_at = NOW();
        """)
        await db.execute(
            upsert_query,
            {
                "symbol_id": symbol_id,
                "broker": broker,
                "strategy": strategy,
                "currency": currency,
                "quantity": qty,
                "avg_buy_price": avg_buy,
                "current_price": current_price,
                "cost_value": cost_val,
                "market_value": market_val,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            },
        )
        records_imported += 1

    await db.commit()

    return {
        "status": "SUCCESS",
        "imported": records_imported,
        "failed_records": records_failed,
        "message": f"Successfully imported {records_imported} holdings into database.",
    }
