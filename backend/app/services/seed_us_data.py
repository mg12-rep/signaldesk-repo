import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv
from ib_insync import IB, Index, Stock, util
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert

load_dotenv()
logger = logging.getLogger("seed_us_universe")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url, pool_size=5, max_overflow=10)


def get_active_us_symbols_from_db() -> List[Dict]:
    """
    Fetches S&P 500 constituents (ID 559), NASDAQ constituents (ID 2978),
    and core ETFs directly from the database.
    """
    query = text("""
        WITH target_stocks AS (
            -- 1. S&P 500 and NASDAQ Constituents
            SELECT DISTINCT i.stock_symbol_id AS symbol_id
            FROM index_constituents i
            WHERE i.index_symbol_id IN (559, 2978)

            UNION

            -- 2. Core Indices & Benchmark/UCITS ETFs
            SELECT id AS symbol_id
            FROM symbols
            WHERE trading_symbol IN ('SPY', 'QQQ', 'IWM', 'SCHD', 'SMH', 'VWRA', 'IB01', 'FUSA', 'IGLN', 'XIU')
        )
        SELECT 
            s.id AS symbol_id,
            s.trading_symbol,
            s.is_index,
            COALESCE(e.code, 'US') AS exchange_code
        FROM target_stocks t
        JOIN symbols s ON s.id = t.symbol_id
        LEFT JOIN exchanges e ON s.exchange_id = e.id
        WHERE s.is_active = TRUE
        ORDER BY s.is_index DESC, s.trading_symbol ASC;
    """)
    with engine.connect() as conn:
        results = conn.execute(query).mappings().all()
        return [dict(r) for r in results]


def get_latest_trade_date(symbol_id: int) -> Optional[date]:
    """Returns the latest available trade date across hot and cold tiers."""
    query = text("""
        SELECT MAX(date) FROM (
            SELECT MAX(date) AS date FROM market_data_eod WHERE symbol_id = :sid
            UNION ALL
            SELECT MAX(date) AS date FROM market_data_history WHERE symbol_id = :sid
        ) t;
    """)
    with engine.connect() as conn:
        return conn.execute(query, {"sid": symbol_id}).scalar()


def build_ibkr_contract(trading_symbol: str, is_index: bool = False) -> object:
    raw_sym = trading_symbol.strip().upper()

    # 1. Pure Indices
    if is_index:
        if raw_sym in ["SPX", "VIX"]:
            return Index(symbol=raw_sym, exchange="CBOE", currency="USD")
        if raw_sym in ["NDX", "COMP"]:
            return Index(symbol=raw_sym, exchange="NASDAQ", currency="USD")
        if raw_sym in ["RUT"]:
            return Index(symbol=raw_sym, exchange="RUSSELL", currency="USD")

    # 2. London / UCITS ETFs (VWRA, IB01, FUSA, IGLN)
    if raw_sym in ["VWRA", "IB01", "FUSA", "IGLN"]:
        return Stock(symbol=raw_sym, exchange="LSEETF", currency="USD")

    # 3. Canadian Equities/ETFs
    if raw_sym in ["XIU"]:
        return Stock(symbol=raw_sym, exchange="TSE", currency="CAD")

    # 4. Standard US Equities & ETFs (S&P 500, NASDAQ 100, Russell 2000)
    clean_sym = raw_sym.replace(".", " ").replace("-", " ").replace("/", " ").strip()
    return Stock(symbol=clean_sym, exchange="SMART", currency="USD")


def fetch_historical_bars_with_retry(
    ib: IB,
    contract: object,
    duration_str: str = "2 Y",
    max_retries: int = 3,
) -> pd.DataFrame:
    """Requests historical daily bars from TWS with rate-limit and pacing handling."""
    try:
        qualified = ib.qualifyContracts(contract)
    except Exception as e:
        logger.warning(
            f"Failed qualifying contract {getattr(contract, 'symbol', '')}: {e}"
        )
        return pd.DataFrame()

    if not qualified:
        logger.warning(
            f"⚠️ Contract qualification failed for: {getattr(contract, 'symbol', '')}"
        )
        return pd.DataFrame()

    for attempt in range(1, max_retries + 1):
        try:
            bars = ib.reqHistoricalData(
                contract=contract,
                endDateTime="",
                durationStr=duration_str,
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )
            if bars:
                df = util.df(bars)
                df["date"] = pd.to_datetime(df["date"]).dt.date
                return df
            return pd.DataFrame()
        except Exception as e:
            err_msg = str(e).lower()
            if "pacing violation" in err_msg or "rate limit" in err_msg:
                backoff = attempt * 12
                logger.warning(
                    f"⏳ Pacing limit hit on {getattr(contract, 'symbol', '')}. Sleeping {backoff}s..."
                )
                time.sleep(backoff)
            else:
                logger.error(
                    f"Error requesting data for {getattr(contract, 'symbol', '')}: {e}"
                )
                break

    return pd.DataFrame()


def bulk_upsert_eod_bars(records: List[dict], table_name: str = "market_data_eod"):
    """
    Executes a high-speed batched upsert using PostgreSQL's ON CONFLICT DO UPDATE.
    """
    if not records:
        return

    # Raw SQL batch execution with ON CONFLICT resolution
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


def _persist_bars(df: pd.DataFrame, symbol_id: int, cutoff_date: date):
    """Partitions and persists bars via bulk_upsert_eod_bars."""
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


def _run_sync_internal(
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 2,
    max_symbols: Optional[int] = None,
):
    """Core synchronization loop querying database symbols table."""
    symbols = get_active_us_symbols_from_db()
    if max_symbols:
        symbols = symbols[:max_symbols]

    total = len(symbols)
    if total == 0:
        logger.warning("No active US symbols found in the symbols table.")
        return

    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, timeout=12)
        logger.info(f"🔌 Connected to IBKR TWS on {host}:{port}")
    except Exception as e:
        logger.error(
            f"❌ Could not connect to IBKR TWS: {e}. Make sure TWS is logged in and API is enabled."
        )
        return

    today = datetime.now().date()
    cutoff_date = today - timedelta(days=365)

    logger.info(f"🚀 Starting ingestion for {total} US symbols from database...")

    success = 0
    skipped = 0
    failed = 0

    try:
        for idx, item in enumerate(symbols, 1):
            sym_id = item["symbol_id"]
            trading_sym = item["trading_symbol"]
            is_index_flag = item["is_index"]

            try:
                latest_date = get_latest_trade_date(sym_id)

                # Skip if already updated today
                if latest_date and latest_date >= today:
                    skipped += 1
                    continue

                if latest_date is None:
                    duration = "2 Y"
                else:
                    delta_days = max((today - latest_date).days + 2, 5)
                    duration = f"{delta_days} D"
                contract = build_ibkr_contract(trading_sym, is_index=is_index_flag)
                df = fetch_historical_bars_with_retry(
                    ib, contract, duration_str=duration
                )

                if df.empty:
                    failed += 1
                    logger.warning(
                        f"[{idx}/{total}] ⚠️ No data returned for {trading_sym}"
                    )
                    continue

                _persist_bars(df, sym_id, cutoff_date)
                success += 1
                logger.info(f"[{idx}/{total}] ✅ {trading_sym} ({len(df)} bars)")

            except Exception as e:
                failed += 1
                logger.error(f"[{idx}/{total}] ❌ Error on {trading_sym}: {e}")

            time.sleep(0.3)

    finally:
        ib.disconnect()
        logger.info(
            f"🎉 Sync Complete: {success} updated, {skipped} up-to-date, {failed} failed out of {total} symbols."
        )


def seed_us_universe_from_db(
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 2,
    max_symbols: Optional[int] = None,
):
    """Entry point with dedicated event loop for background execution."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        _run_sync_internal(
            host=host, port=port, client_id=client_id, max_symbols=max_symbols
        )
    finally:
        loop.close()


if __name__ == "__main__":
    seed_us_universe_from_db(max_symbols=None)
