import logging
import os
import time

from app.services.ingest_data import archive_older_bars, ingest_stock_bars
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
logger = logging.getLogger("seed_all_symbols")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url)


def get_all_active_symbols() -> list[dict]:
    """Fetches all active symbols registered in the symbols table."""
    query = text("""
        SELECT trading_symbol, is_index
        FROM symbols
        WHERE is_active = TRUE
        ORDER BY is_index DESC, trading_symbol ASC;
    """)
    with engine.connect() as conn:
        result = conn.execute(query).mappings().all()
        return [dict(r) for r in result]


def run_full_universe_sync(full_seed_years: int = 4):
    """Iterates through every symbol in the DB and performs smart ingestion."""
    symbols = get_all_active_symbols()
    total = len(symbols)

    if total == 0:
        logger.warning("No active symbols found in the symbols table.")
        return

    logger.info(f"🚀 Starting ingestion for all {total} symbols in database...")

    success_count = 0
    skipped_count = 0
    failed_count = 0

    for idx, item in enumerate(symbols, 1):
        sym = item["trading_symbol"]
        is_index = item["is_index"]

        try:
            bars_count = ingest_stock_bars(
                symbol=sym,
                is_index=is_index,
                full_seed_years=full_seed_years,
                exchange_code="NSE",
            )
            if bars_count > 0:
                success_count += 1
            else:
                skipped_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(f"❌ [{idx}/{total}] Error ingesting {sym}: {e}")

        # Throttle to stay within broker API rate limits
        time.sleep(0.06)

    logger.info(f"📦 Running Cold Tier Archive (>365 days)...")
    archive_older_bars()

    logger.info(
        f"🎉 Full sync complete: {success_count} updated, {skipped_count} up-to-date, {failed_count} failed out of {total} total symbols."
    )


if __name__ == "__main__":
    run_full_universe_sync()
