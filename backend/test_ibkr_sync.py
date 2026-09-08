import asyncio

from app.db.session import AsyncSessionLocal
from app.services.brokers.ibkr_adapter import ibkr_adapter
from app.services.sync_service import sync_broker_portfolio
from sqlalchemy import text


async def test_ibkr_integration():
    print("--- 1. Testing IBKR Connection & Adapter Fetch ---")
    try:
        cash = ibkr_adapter.get_cash_balance()
        print(f"💰 Available Cash Balance: USD {cash:,.2f}")

        holdings = ibkr_adapter.get_holdings()
        print(f"📦 Total Positions fetched from IBKR: {len(holdings)}")
        for h in holdings:
            print(
                f"   Ticker: {h['tradingsymbol']} | Qty: {h['quantity']} | AvgCost: {h['average_price']:.2f} | LTP: {h['last_price']:.2f} | PnL: {h['pnl']:.2f}"
            )
    except Exception as e:
        print(f"❌ Adapter connection failed: {e}")
        return

    print("\n--- 2. Running Portfolio Sync Service for IBKR ---")
    async with AsyncSessionLocal() as db:
        try:
            res = await sync_broker_portfolio(
                db=db, broker="IBKR", default_strategy="minervini_vcp"
            )
            print(f"✅ Sync Result: {res}")
        except Exception as e:
            print(f"❌ Sync failed with exception: {e}")

    print("\n--- 3. Verifying Holdings in Database for IBKR ---")
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text("""
            SELECT h.id, s.trading_symbol, h.broker, h.strategy, h.quantity, h.avg_buy_price, h.updated_at
            FROM holdings h
            JOIN symbols s ON h.symbol_id = s.id
            WHERE h.broker = 'IBKR';
        """)
        )
        db_holdings = rows.mappings().all()
        print(f"Total rows in DB for IBKR: {len(db_holdings)}")
        for row in db_holdings:
            print(
                f"   ID: {row['id']} | {row['trading_symbol']} | Strategy: {row['strategy']} | Qty: {row['quantity']} | Avg: {row['avg_buy_price']} | Updated: {row['updated_at']}"
            )


if __name__ == "__main__":
    asyncio.run(test_ibkr_integration())
