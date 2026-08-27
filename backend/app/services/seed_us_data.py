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

load_dotenv()
logger = logging.getLogger("seed_us_universe")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url)

EXCHANGE_TO_IBKR_MAP = {
    "NASDAQ": {"exchange": "SMART", "primaryExchange": "NASDAQ", "currency": "USD"},
    "NYSE": {"exchange": "SMART", "primaryExchange": "NYSE", "currency": "USD"},
    "AMEX": {"exchange": "SMART", "primaryExchange": "AMEX", "currency": "USD"},
    "US": {"exchange": "SMART", "currency": "USD"},
    "LSE": {"exchange": "LSEETF", "currency": "USD"},
    "TSX": {"exchange": "TSE", "currency": "CAD"},
}


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


def update_symbol_exchange(symbol_id: int, detected_exchange: str):
    """Updates the exchange_id in the symbols table based on IBKR qualification."""
    if not detected_exchange:
        return
    with engine.begin() as conn:
        # Get or create exchange
        exch_id = conn.execute(
            text("""
                INSERT INTO exchanges (code, name, country, timezone)
                VALUES (:code, :name, 'US', 'America/New_York')
                ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code
                RETURNING id;
            """),
            {"code": detected_exchange.upper(), "name": detected_exchange.upper()},
        ).scalar()

        # Update symbol mapping
        conn.execute(
            text("UPDATE symbols SET exchange_id = :exch_id WHERE id = :sid"),
            {"exch_id": exch_id, "sid": symbol_id},
        )


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
    # Convert dots/hyphens/slashes to spaces (e.g., BRK.B -> BRK B, BF.B -> BF B)
    clean_sym = raw_sym.replace(".", " ").replace("-", " ").replace("/", " ").strip()

    # Do NOT specify primaryExchange here so IBKR auto-resolves between NASDAQ, NYSE, and ARCA
    return Stock(symbol=clean_sym, exchange="SMART", currency="USD")


def fetch_historical_bars_with_retry(
    ib: IB,
    contract: Stock,
    symbol_id: int,
    duration_str: str = "4 Y",
    max_retries: int = 3,
) -> pd.DataFrame:
    """Requests historical daily bars from TWS with rate-limit and pacing handling."""
    try:
        qualified = ib.qualifyContracts(contract)
    except Exception as e:
        logger.warning(f"Failed qualifying contract {contract.symbol}: {e}")
        return pd.DataFrame()

    if not qualified:
        logger.warning(f"⚠️ Contract qualification failed for: {contract.symbol}")
        return pd.DataFrame()

    if contract.primaryExchange:
        try:
            update_symbol_exchange(symbol_id, contract.primaryExchange)
        except Exception as e:
            logger.warning(f"Could not update exchange for {contract.symbol}: {e}")

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
                    f"⏳ Pacing limit hit on {contract.symbol}. Sleeping {backoff}s..."
                )
                time.sleep(backoff)
            else:
                logger.error(f"Error requesting data for {contract.symbol}: {e}")
                break

    return pd.DataFrame()


def _persist_bars(df: pd.DataFrame, symbol_id: int, cutoff_date: date):
    """Upserts partitioned bars into market_data_eod and market_data_history."""
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
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO market_data_eod (symbol_id, date, open, high, low, close, adj_close, volume)
                VALUES (:symbol_id, :date, :open, :high, :low, :close, :adj_close, :volume)
                ON CONFLICT (symbol_id, date) DO UPDATE SET
                    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                    close=EXCLUDED.close, adj_close=EXCLUDED.adj_close, volume=EXCLUDED.volume;
            """),
                eod_records,
            )

    if hist_records:
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO market_data_history (symbol_id, date, open, high, low, close, adj_close, volume)
                VALUES (:symbol_id, :date, :open, :high, :low, :close, :adj_close, :volume)
                ON CONFLICT (symbol_id, date) DO UPDATE SET
                    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                    close=EXCLUDED.close, adj_close=EXCLUDED.adj_close, volume=EXCLUDED.volume;
            """),
                hist_records,
            )


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
            exch_code = item["exchange_code"]

            try:
                latest_date = get_latest_trade_date(sym_id)

                # Skip if already updated today
                if latest_date and latest_date >= today:
                    skipped += 1
                    continue

                duration = (
                    "4 Y"
                    if latest_date is None
                    else f"{(today - latest_date).days + 2} D"
                )
                contract = build_ibkr_contract(trading_sym, exch_code)
                df = fetch_historical_bars_with_retry(
                    ib, contract, sym_id, duration_str=duration
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

            # 1.2s delay to comply with IBKR pacing restrictions
            time.sleep(1.2)

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
    # Test with first 10 symbols, or pass max_symbols=None for full universe
    seed_us_universe_from_db(max_symbols=None)
