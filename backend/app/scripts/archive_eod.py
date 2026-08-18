import asyncio
from datetime import date, timedelta

from app.db.session import AsyncSessionLocal
from sqlalchemy import text


async def archive_old_eod_data():
    """Moves market_data_eod records older than 365 days into market_data_history."""
    print("🚀 Starting Weekly Hot-to-Cold Archiver Job...")

    cutoff_date = date.today() - timedelta(days=365)
    print(f"📅 Moving records older than: {cutoff_date}")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # 1. Copy old data from EOD to History
            move_query = text("""
                INSERT INTO market_data_history (id, symbol_id, date, open, high, low, close, adj_close, volume)
                SELECT id, symbol_id, date, open, high, low, close, adj_close, volume
                FROM market_data_eod
                WHERE date < :cutoff
                ON CONFLICT (symbol_id, date) DO NOTHING;
            """)
            res_move = await session.execute(move_query, {"cutoff": cutoff_date})

            # 2. Delete moved records from Hot EOD table
            delete_query = text("""
                DELETE FROM market_data_eod
                WHERE date < :cutoff;
            """)
            res_delete = await session.execute(delete_query, {"cutoff": cutoff_date})

            print(f"✅ Archiver Complete: Archived & purged {res_delete.rowcount} records from `market_data_eod`.")


if __name__ == "__main__":
    asyncio.run(archive_old_eod_data())