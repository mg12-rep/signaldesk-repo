import concurrent.futures
import logging
import os
import time
from typing import Dict, List

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

# Configured connection pool for multi-threaded worker execution
engine = create_engine(sync_db_url, pool_size=15, max_overflow=10, pool_pre_ping=True)


def get_all_active_symbols() -> List[Dict]:
    """Fetches all active NSE symbols registered in the symbols table."""
    query = text("""
        SELECT s.trading_symbol, s.is_index
        FROM symbols s
        JOIN exchanges e ON s.exchange_id = e.id
        WHERE s.is_active = TRUE AND e.code = 'NSE'
        ORDER BY s.is_index DESC, s.trading_symbol ASC;
    """)
    with engine.connect() as conn:
        result = conn.execute(query).mappings().all()
        return [dict(r) for r in result]


def _process_single_symbol(item: Dict, full_seed_years: int) -> tuple[str, str, int]:
    """Worker task executed by thread pool."""
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
            return sym, "SUCCESS", bars_count
        else:
            return sym, "SKIPPED", 0
    except Exception as e:
        logger.error(f"❌ Error ingesting {sym}: {e}")
        return sym, "FAILED", 0


def run_full_universe_sync(full_seed_years: int = 2, max_workers: int = 8):
    """
    Concurrent universe ingestion pipeline using ThreadPoolExecutor.
    max_workers=8 stays well within Upstox rate limits while offering 6-8x speedups.
    """
    symbols = get_all_active_symbols()
    total = len(symbols)

    if total == 0:
        logger.warning("No active symbols found in the symbols table.")
        return

    logger.info(
        f"🚀 Starting parallel ingestion for {total} NSE symbols (Workers: {max_workers})..."
    )
    start_time = time.time()

    success_count = 0
    skipped_count = 0
    failed_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_symbol = {
            executor.submit(_process_single_symbol, item, full_seed_years): item[
                "trading_symbol"
            ]
            for item in symbols
        }

        # Collect results as they complete
        for idx, future in enumerate(
            concurrent.futures.as_completed(future_to_symbol), 1
        ):
            sym = future_to_symbol[future]
            try:
                sym_name, status, bars = future.result()
                if status == "SUCCESS":
                    success_count += 1
                    if idx % 25 == 0 or idx == total:
                        logger.info(f"[{idx}/{total}] ✅ {sym_name} ({bars} bars)")
                elif status == "SKIPPED":
                    skipped_count += 1
                else:
                    failed_count += 1
            except Exception as exc:
                failed_count += 1
                logger.error(f"[{idx}/{total}] ❌ {sym} generated an exception: {exc}")

    elapsed = round(time.time() - start_time, 2)
    logger.info(
        f"⚡ Ingestion finished in {elapsed}s. Archiving cold tier (>365 days)..."
    )
    archive_older_bars()

    logger.info(
        f"🎉 Full sync complete in {elapsed}s: {success_count} updated, {skipped_count} up-to-date, {failed_count} failed out of {total} symbols."
    )


if __name__ == "__main__":
    run_full_universe_sync(full_seed_years=2, max_workers=8)
