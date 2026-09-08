import asyncio

from app.db.session import AsyncSessionLocal
from app.services.sync_service import sync_broker_portfolio
from sqlalchemy import text


async def debug_full_sync():
    print("--- 1. Testing Raw Adapter Fetch ---")
    from app.services.brokers.zerodha_adapter import zerodha_adapter

    raw = zerodha_adapter.get_holdings()
    print(f"Total CNC Holdings fetched from Zerodha: {len(raw)}")
    for item in raw[:5]:
        print(
            f"  Ticker: {item.get('tradingsymbol')}, Qty: {item.get('quantity')}, T1: {item.get('t1_quantity')}, AvgPrice: {item.get('average_price')}"
        )

    print("\n--- 2. Executing Broker Sync Function ---")
    async with AsyncSessionLocal() as db:
        try:
            res = await sync_broker_portfolio(
                db=db, broker="ZERODHA", default_strategy="minervini_vcp"
            )
            print(f"Sync Result: {res}")
        except Exception as e:
            print(f"❌ Sync failed with exception: {e}")

    print("\n--- 3. Checking Holdings Table in Database ---")
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text("""
            SELECT h.id, s.trading_symbol, h.broker, h.strategy, h.quantity, h.avg_buy_price, h.updated_at
            FROM holdings h
            JOIN symbols s ON h.symbol_id = s.id
            WHERE h.broker = 'ZERODHA';
        """)
        )
        holdings = rows.mappings().all()
        print(f"Total rows in DB for ZERODHA: {len(holdings)}")
        for h in holdings:
            print(
                f"  Holding ID: {h['id']} | {h['trading_symbol']} | Strategy: {h['strategy']} | Qty: {h['quantity']} | Avg: {h['avg_buy_price']} | Updated: {h['updated_at']}"
            )


if __name__ == "__main__":
    asyncio.run(debug_full_sync())
