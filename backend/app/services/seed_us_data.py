import argparse
import asyncio
import csv
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from app.services.brokers.ibkr_adapter import ibkr_adapter
from dotenv import load_dotenv
from ib_async import IB, Index, Stock, util
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

load_dotenv()
logger = logging.getLogger("seed_us_universe")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url, pool_size=5, max_overflow=10)


def get_active_us_symbols_and_dates() -> List[Dict]:
    """
    Fetches active US symbols (S&P 500 / NASDAQ 100 constituents + priority ETFs)
    and their latest trade dates in a single SQL roundtrip.
    """
    query = text("""
        WITH target_stocks AS (
            SELECT DISTINCT i.stock_symbol_id AS symbol_id
            FROM index_constituents i
            WHERE i.index_symbol_id IN (559, 2978)

            UNION

            SELECT id AS symbol_id
            FROM symbols
            WHERE trading_symbol IN ('SPY', 'QQQ', 'IWM', 'SCHD', 'SMH', 'VWRA', 'IB01', 'FUSA', 'IGLN', 'XIU')
        ),
        latest_eod AS (
            SELECT symbol_id, MAX(date) AS latest_eod_date
            FROM market_data_eod
            GROUP BY symbol_id
        ),
        latest_hist AS (
            SELECT symbol_id, MAX(date) AS latest_hist_date
            FROM market_data_history
            GROUP BY symbol_id
        )
        SELECT 
            s.id AS symbol_id,
            s.trading_symbol,
            s.is_index,
            COALESCE(e.code, 'US') AS exchange_code,
            GREATEST(le.latest_eod_date, lh.latest_hist_date) AS latest_date
        FROM target_stocks t
        JOIN symbols s ON s.id = t.symbol_id
        LEFT JOIN exchanges e ON s.exchange_id = e.id
        LEFT JOIN latest_eod le ON s.id = le.symbol_id
        LEFT JOIN latest_hist lh ON s.id = lh.symbol_id
        WHERE s.is_active = TRUE
        ORDER BY s.is_index DESC, s.trading_symbol ASC;
    """)
    with engine.connect() as conn:
        results = conn.execute(query).mappings().all()
        return [dict(r) for r in results]


def get_custom_us_symbols_and_dates(csv_path: str) -> List[Dict]:
    """
    Reads tickers from a custom CSV or text file and resolves their symbol_ids
    and latest dates from the database.
    """
    p = Path(csv_path)
    if not p.is_file():
        logger.error(f"Custom US file not found: {csv_path}")
        return []

    raw_symbols = set()
    with open(p, mode="r", encoding="utf-8-sig") as f:
        sample = f.read(1024)
        f.seek(0)
        if "," in sample:
            reader = csv.DictReader(f)
            for row in reader:
                sym = (
                    row.get("ticker")
                    or row.get("Symbol")
                    or row.get("SYMBOL")
                    or row.get("trading_symbol")
                )
                if sym:
                    raw_symbols.add(sym.strip().upper())
        else:
            for line in f:
                sym = line.strip().upper()
                if sym and not sym.startswith("#"):
                    raw_symbols.add(sym)

    if not raw_symbols:
        logger.warning(f"No symbols found in file: {csv_path}")
        return []

    query = text("""
        WITH target_stocks AS (
            SELECT id AS symbol_id
            FROM symbols
            WHERE UPPER(trading_symbol) = ANY(:symbols) AND is_active = TRUE
        ),
        latest_eod AS (
            SELECT symbol_id, MAX(date) AS latest_eod_date
            FROM market_data_eod
            GROUP BY symbol_id
        ),
        latest_hist AS (
            SELECT symbol_id, MAX(date) AS latest_hist_date
            FROM market_data_history
            GROUP BY symbol_id
        )
        SELECT 
            s.id AS symbol_id,
            s.trading_symbol,
            s.is_index,
            COALESCE(e.code, 'US') AS exchange_code,
            GREATEST(le.latest_eod_date, lh.latest_hist_date) AS latest_date
        FROM target_stocks t
        JOIN symbols s ON s.id = t.symbol_id
        LEFT JOIN exchanges e ON s.exchange_id = e.id
        LEFT JOIN latest_eod le ON s.id = le.symbol_id
        LEFT JOIN latest_hist lh ON s.id = lh.symbol_id
        ORDER BY s.is_index DESC, s.trading_symbol ASC;
    """)

    with engine.connect() as conn:
        results = conn.execute(query, {"symbols": list(raw_symbols)}).mappings().all()
        matched = [dict(r) for r in results]

    matched_symbols = {r["trading_symbol"].upper() for r in matched}
    missing = raw_symbols - matched_symbols
    if missing:
        logger.warning(
            f"⚠ {len(missing)} tickers from '{csv_path}' not found in DB symbols table: {sorted(list(missing))[:10]}..."
        )

    logger.info(
        f"🎯 Matched {len(matched)}/{len(raw_symbols)} US symbols from '{csv_path}' against DB."
    )
    return matched


def build_ibkr_contract(trading_symbol: str, is_index: bool = False) -> object:
    raw_sym = trading_symbol.strip().upper()

    if is_index:
        if raw_sym in ["SPX", "VIX"]:
            return Index(symbol=raw_sym, exchange="CBOE", currency="USD")
        if raw_sym in ["NDX", "COMP"]:
            return Index(symbol=raw_sym, exchange="NASDAQ", currency="USD")
        if raw_sym in ["RUT"]:
            return Index(symbol=raw_sym, exchange="RUSSELL", currency="USD")

    if raw_sym in ["VWRA", "IB01", "FUSA", "IGLN"]:
        return Stock(symbol=raw_sym, exchange="LSEETF", currency="USD")

    if raw_sym in ["XIU"]:
        return Stock(symbol=raw_sym, exchange="TSE", currency="CAD")

    clean_sym = raw_sym.replace(".", " ").replace("-", " ").replace("/", " ").strip()
    return Stock(symbol=clean_sym, exchange="SMART", currency="USD")


def bulk_upsert_eod_bars(records: List[dict], table_name: str = "market_data_eod"):
    if not records:
        return

    query = text(f"""
        INSERT INTO {table_name} (symbol_id, date, open, high, low, close, adj_close, volume)
        VALUES (:symbol_id, :date, :open, :high, :low, :close, :adj_close, :volume)
        ON CONFLICT (symbol_id, date) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            adj_close = EXCLUDED.adj_close,
            volume = EXCLUDED.volume;
    """)

    with engine.begin() as conn:
        conn.execute(query, records)


def _partition_and_persist(df: pd.DataFrame, symbol_id: int, cutoff_date: date):
    eod_records = []
    hist_records = []

    for _, row in df.iterrows():
        trade_date = row["date"]
        record = {
            "symbol_id": symbol_id,
            "date": trade_date,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "adj_close": float(row["close"]),
            "volume": int(row["volume"]),
        }
        if trade_date >= cutoff_date:
            eod_records.append(record)
        else:
            hist_records.append(record)

    if eod_records:
        bulk_upsert_eod_bars(eod_records, table_name="market_data_eod")
    if hist_records:
        bulk_upsert_eod_bars(hist_records, table_name="market_data_history")


async def _fetch_and_process_symbol(
    ib: IB,
    item: Dict,
    semaphore: asyncio.Semaphore,
    today: date,
    cutoff_date: date,
    stats: Dict[str, int],
):
    sym_id = item["symbol_id"]
    trading_sym = item["trading_symbol"]
    is_index_flag = item["is_index"]
    latest_date = item["latest_date"]

    # 1. Skip if already synced today
    if latest_date and latest_date >= today:
        stats["skipped"] += 1
        return

    duration = (
        "2 Y" if latest_date is None else f"{max((today - latest_date).days + 2, 5)} D"
    )

    contract = build_ibkr_contract(trading_sym, is_index_flag)

    async with semaphore:
        try:
            qualified = await asyncio.wait_for(
                ib.qualifyContractsAsync(contract), timeout=2.5
            )
            if not qualified or not contract.conId:
                logger.warning(f"⚠️ Could not qualify contract: {trading_sym}")
                stats["failed"] += 1
                return
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"⚠️ Qualification timed out/failed for {trading_sym}: {e}")
            stats["failed"] += 1
            return

        for attempt in range(1, 4):
            try:
                bars = await ib.reqHistoricalDataAsync(
                    contract=contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting="1 day",
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=1,
                )
                if bars:
                    df = util.df(bars)
                    df["date"] = pd.to_datetime(df["date"]).dt.date
                    _partition_and_persist(df, sym_id, cutoff_date)
                    stats["success"] += 1
                    logger.info(f"✅ {trading_sym} ({len(df)} bars)")
                    await asyncio.sleep(0.1)
                    return
                else:
                    stats["failed"] += 1
                    logger.warning(f"⚠️ Empty bars returned for {trading_sym}")
                    return

            except Exception as e:
                err_msg = str(e).lower()
                if "pacing" in err_msg or "rate limit" in err_msg:
                    backoff = attempt * 10
                    logger.warning(
                        f"⏳ Pacing limit on {trading_sym}. Backing off {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(f"❌ Error on {trading_sym}: {e}")
                    break

        stats["failed"] += 1


async def _run_sync_async(
    symbols: List[Dict],
    host: str = "127.0.0.1",
    port: int = 4001,
    client_id: int = 99,
    concurrency_limit: int = 4,
):
    total = len(symbols)
    if total == 0:
        logger.warning("No active US symbols found to process.")
        return

    ib = IB()
    try:
        await ib.connectAsync(host, port, clientId=client_id, timeout=12)
        logger.info(f"🔌 Connected to IBKR TWS on {host}:{port}")
    except Exception as e:
        logger.error(f"❌ Could not connect to IBKR TWS: {e}")
        return

    today = datetime.now().date()
    cutoff_date = today - timedelta(days=365)

    logger.info(
        f"🚀 Starting parallel ingestion for {total} symbols (Concurrency: {concurrency_limit})..."
    )
    semaphore = asyncio.Semaphore(concurrency_limit)
    stats = {"success": 0, "skipped": 0, "failed": 0}

    tasks = [
        _fetch_and_process_symbol(ib, item, semaphore, today, cutoff_date, stats)
        for item in symbols
    ]
    await asyncio.gather(*tasks)

    ib.disconnect()
    logger.info(
        f"🎉 Sync Complete: {stats['success']} updated, {stats['skipped']} skipped, {stats['failed']} failed out of {total} symbols."
    )


def seed_us_universe_from_db(
    host: str = "127.0.0.1",
    port: int = 4001,
    client_id: int = 99,
    max_symbols: Optional[int] = None,
):
    """Syncs S&P 500 / NASDAQ 100 universe loaded from database."""
    symbols = get_active_us_symbols_and_dates()
    if max_symbols:
        symbols = symbols[:max_symbols]
    asyncio.run(
        _run_sync_async(
            symbols=symbols, host=host, port=port, client_id=client_id
        )
    )


def seed_us_custom_from_file(
    csv_path: str,
    host: str = "127.0.0.1",
    port: int = 4001,
    client_id: int = 99,
):
    """Syncs US symbols listed in a custom CSV or text file."""
    symbols = get_custom_us_symbols_and_dates(csv_path)
    if not symbols:
        return
    asyncio.run(
        _run_sync_async(
            symbols=symbols, host=host, port=port, client_id=client_id
        )
    )


async def sync_us_etf_market_data(
    db: AsyncSession,
    csv_path: str = "C:/Work/signaldesk/data/US_ETF_Tickers.csv",
    delay_between_calls: float = 1.1,
) -> Dict[str, Any]:
    file_path = Path(csv_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Ticker file {csv_path} not found.")

    df_tickers = pd.read_csv(file_path)
    tickers = df_tickers["ticker"].dropna().str.strip().unique().tolist()

    today = datetime.now().date()
    cutoff_date = today - timedelta(days=365)

    batch_queue: List[Dict[str, Any]] = []
    symbol_meta: Dict[str, Dict[str, Any]] = {}
    skipped_count = 0

    for ticker in tickers:
        sym = ticker.upper()

        res = await db.execute(
            text("SELECT id FROM symbols WHERE UPPER(trading_symbol) = :sym LIMIT 1;"),
            {"sym": sym},
        )
        row = res.mappings().first()
        if row:
            symbol_id = row["id"]
            await db.execute(
                text(
                    "UPDATE symbols SET asset_class = 'ETF', is_active = TRUE WHERE id = :id;"
                ),
                {"id": symbol_id},
            )
        else:
            ins = await db.execute(
                text("""
                    INSERT INTO symbols (trading_symbol, name, exchange_id, is_index, asset_class, is_active)
                    VALUES (:sym, :name, 12, FALSE, 'ETF', TRUE)
                    RETURNING id;
                """),
                {"sym": sym, "name": f"{sym} ETF"},
            )
            symbol_id = ins.scalar()

        date_res = await db.execute(
            text(
                "SELECT MAX(date) AS max_date FROM market_data_all WHERE symbol_id = :sid;"
            ),
            {"sid": symbol_id},
        )
        last_date = date_res.scalar()

        if last_date is None:
            duration_str = "2 Y"
        else:
            days_missing = (today - last_date).days
            if days_missing <= 0:
                skipped_count += 1
                continue
            buffer_days = max(days_missing + 2, 5)
            duration_str = f"{buffer_days} D"

        batch_queue.append({"symbol": sym, "duration": duration_str})
        symbol_meta[sym] = {"symbol_id": symbol_id, "last_date": last_date}

    await db.commit()

    if not batch_queue:
        return {
            "total_tickers": len(tickers),
            "synced": 0,
            "skipped": skipped_count,
            "failed": [],
        }

    logger.info(f"Queued {len(batch_queue)} ETF(s) for single-session batch sync...")

    fetched_data = ibkr_adapter.fetch_multiple_etf_bars(
        batch_queue, delay_seconds=delay_between_calls
    )

    synced_count = 0
    failed_tickers = [
        item["symbol"] for item in batch_queue if item["symbol"] not in fetched_data
    ]

    upsert_stmt = """
        INSERT INTO {table} (symbol_id, date, open, high, low, close, adj_close, volume)
        VALUES (:symbol_id, :date, :open, :high, :low, :close, :adj_close, :volume)
        ON CONFLICT (symbol_id, date) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, adj_close = EXCLUDED.adj_close, volume = EXCLUDED.volume;
    """

    for sym, bars_df in fetched_data.items():
        if bars_df.empty:
            failed_tickers.append(sym)
            continue

        meta = symbol_meta.get(sym, {})
        last_date = meta.get("last_date")
        symbol_id = meta.get("symbol_id")

        if last_date is not None:
            bars_df = bars_df[bars_df["date"] >= last_date]
            if bars_df.empty:
                skipped_count += 1
                continue

        bars_df["symbol_id"] = symbol_id
        eod_df = bars_df[bars_df["date"] >= cutoff_date]
        hist_df = bars_df[bars_df["date"] < cutoff_date]

        if not eod_df.empty:
            for record in eod_df.to_dict(orient="records"):
                await db.execute(
                    text(upsert_stmt.format(table="market_data_eod")), record
                )

        if not hist_df.empty:
            for record in hist_df.to_dict(orient="records"):
                await db.execute(
                    text(upsert_stmt.format(table="market_data_history")), record
                )

        synced_count += 1

    await db.commit()
    logger.info(
        f"Batch completed: Synced={synced_count}, Skipped={skipped_count}, Failed={len(failed_tickers)}"
    )

    return {
        "total_tickers": len(tickers),
        "synced": synced_count,
        "skipped": skipped_count,
        "failed": failed_tickers,
    }


def run_us_etf_sync_standalone():
    from app.db.session import AsyncSessionLocal

    async def _execute():
        async with AsyncSessionLocal() as session:
            return await sync_us_etf_market_data(session)

    return asyncio.run(_execute())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="US Market Data Ingestion Pipeline")
    parser.add_argument(
        "--mode",
        choices=["sp500", "custom"],
        default="sp500",
        help="Sync mode: sp500 or custom (default: sp500)",
    )
    parser.add_argument(
        "--custom-file",
        type=str,
        default=None,
        help="Path to custom CSV or text file containing US symbols",
    )
    args = parser.parse_args()

    if args.mode == "custom" and args.custom_file:
        seed_us_custom_from_file(args.custom_file)
    else:
        seed_us_universe_from_db(max_symbols=None)
        run_us_etf_sync_standalone()