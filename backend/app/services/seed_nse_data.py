import argparse
import concurrent.futures
import csv
import logging
import os
from pathlib import Path
import time
from typing import Dict, List, Optional

from app.services.ingest_data import archive_older_bars, ingest_stock_bars
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
logger = logging.getLogger("seed_nse_symbols")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)

# Configured connection pool for multi-threaded worker execution
engine = create_engine(sync_db_url, pool_size=15, max_overflow=10, pool_pre_ping=True)


def get_nifty500_symbols() -> List[Dict]:
    """Fetches Nifty 500 index constituents + index itself from the database."""
    query = text("""
        SELECT s.trading_symbol, s.is_index
        FROM symbols s
        WHERE s.id = 2 AND s.is_active = TRUE
        UNION
        SELECT s.trading_symbol, s.is_index
        FROM index_constituents ic
        JOIN symbols s ON ic.stock_symbol_id = s.id
        WHERE ic.index_symbol_id = 2 AND s.is_active = TRUE
        ORDER BY is_index DESC, trading_symbol ASC;
    """)
    with engine.connect() as conn:
        result = conn.execute(query).mappings().all()
        return [dict(r) for r in result]


def load_symbols_from_file(file_path: str) -> List[Dict]:
    """
    Reads custom symbols from a CSV or text file.
    Validates them against the database symbols table (independent of Nifty 500).
    """
    p = Path(file_path)
    if not p.is_file():
        logger.error(f"Custom symbols file not found: {file_path}")
        return []

    raw_symbols = set()
    with open(p, mode="r", encoding="utf-8-sig") as f:
        sample = f.read(1024)
        f.seek(0)
        if "," in sample:
            reader = csv.DictReader(f)
            for row in reader:
                sym = (
                    row.get("trading_symbol")
                    or row.get("Symbol")
                    or row.get("SYMBOL")
                    or row.get("symbol")
                )
                if sym:
                    raw_symbols.add(sym.strip().upper())
        else:
            for line in f:
                sym = line.strip().upper()
                if sym and not sym.startswith("#"):
                    raw_symbols.add(sym)

    if not raw_symbols:
        logger.warning(f"No symbols found in file: {file_path}")
        return []

    query = text("""
        SELECT s.trading_symbol, s.is_index
        FROM symbols s
        JOIN exchanges e ON s.exchange_id = e.id
        WHERE e.code = 'NSE'
          AND s.is_active = TRUE
          AND UPPER(s.trading_symbol) = ANY(:symbols);
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {"symbols": list(raw_symbols)}).mappings().all()
        valid_symbols = [dict(r) for r in result]

    found_names = {s["trading_symbol"].upper() for s in valid_symbols}
    missing = raw_symbols - found_names
    if missing:
        logger.warning(
            f"⚠️️ {len(missing)} custom symbols are not registered/active in the symbols table: {sorted(list(missing))[:10]}..."
        )

    logger.info(
        f"🎯 Validated {len(valid_symbols)}/{len(raw_symbols)} custom symbols against NSE database registry."
    )
    return valid_symbols


def _process_single_symbol(
    item: Dict, full_seed_years: int
) -> tuple[str, str, int]:
    """Worker task executed by thread pool."""
    sym = item["trading_symbol"]
    is_index = item.get("is_index", False)
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


def run_sync(
    mode: str = "nifty500",
    custom_file: Optional[str] = None,
    full_seed_years: int = 2,
    max_workers: int = 8,
):
    """Executes either Nifty 500 universe or custom CSV file sync."""
    if mode == "custom" and custom_file:
        symbols = load_symbols_from_file(custom_file)
        logger.info(
            f"📁 Loaded {len(symbols)} symbols from custom file: {custom_file}"
        )
    elif mode == "nifty500":
        symbols = get_nifty500_symbols()
        logger.info(
            f"🇮🇳 Loaded {len(symbols)} Nifty 500 constituents from database."
        )
    else:
        logger.error(f"Unknown mode '{mode}' or missing custom file.")
        return

    total = len(symbols)
    if total == 0:
        logger.warning("No symbols to ingest.")
        return

    logger.info(
        f"🚀 Starting parallel ingestion for {total} NSE symbols (Workers: {max_workers}, Years: {full_seed_years})..."
    )
    start_time = time.time()

    success_count = 0
    skipped_count = 0
    failed_count = 0

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:
        future_to_symbol = {
            executor.submit(
                _process_single_symbol, item, full_seed_years
            ): item["trading_symbol"]
            for item in symbols
        }

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
        f"🎉 Sync complete in {elapsed}s: {success_count} updated, {skipped_count} up-to-date, {failed_count} failed out of {total} symbols."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NSE Data Ingestion Pipeline")
    parser.add_argument(
        "--mode",
        choices=["nifty500", "custom"],
        default="nifty500",
        help="Sync mode: nifty500 or custom (default: nifty500)",
    )
    parser.add_argument(
        "--custom-file",
        type=str,
        default=None,
        help="Path to custom CSV or text file containing symbols",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=2,
        help="Number of historical years to fetch",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of concurrent worker threads",
    )
    args = parser.parse_args()

    run_sync(
        mode=args.mode,
        custom_file=args.custom_file,
        full_seed_years=args.years,
        max_workers=args.workers,
    )