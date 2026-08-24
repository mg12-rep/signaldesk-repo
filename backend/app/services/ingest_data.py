import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
from app.services.brokers.upstox_adapter import upstox_adapter
from app.services.upstox_instruments import upstox_instruments
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
logger = logging.getLogger("ingest_market_data")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Ensure synchronous psycopg2 connection for bulk inserts
raw_db_url = os.getenv("DATABASE_URL", "")
sync_db_url = raw_db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
engine = create_engine(sync_db_url)


def get_or_create_exchange_id(
    conn,
    code: str = "NSE",
    name: str = "National Stock Exchange of India",
    country: str = "IN",
    timezone: str = "Asia/Kolkata",
) -> int:
    """Ensures the exchange exists in the database and returns its ID."""
    res = conn.execute(
        text("SELECT id FROM exchanges WHERE UPPER(code) = :code"),
        {"code": code.upper()},
    ).scalar()

    if res:
        return res

    ins = conn.execute(
        text("""
            INSERT INTO exchanges (code, name, country, timezone)
            VALUES (:code, :name, :country, :timezone)
            RETURNING id;
        """),
        {"code": code.upper(), "name": name, "country": country, "timezone": timezone},
    )
    return ins.scalar()


def get_or_create_symbol_id(
    trading_symbol: str, is_index: bool = False, exchange_code: str = "NSE"
) -> int:
    """Fetches symbol_id from symbols table or creates a new entry with exchange_id."""
    with engine.begin() as conn:
        res = conn.execute(
            text("SELECT id FROM symbols WHERE UPPER(trading_symbol) = :sym"),
            {"sym": trading_symbol.upper()},
        ).scalar()

        if res:
            return res

        # Resolve foreign key exchange_id
        exchange_id = get_or_create_exchange_id(conn, code=exchange_code)
        logging.debug(f"exchange_Id {exchange_id}")

        # Insert new symbol record
        ins = conn.execute(
            text("""
                INSERT INTO symbols (trading_symbol, name, exchange_id, is_index, asset_class, is_active)
                VALUES (:sym, :name, :exchange_id, :is_index, 'EQUITY', TRUE)
                RETURNING id;
            """),
            {
                "sym": trading_symbol.upper(),
                "name": trading_symbol.upper(),
                "exchange_id": exchange_id,
                "is_index": is_index,
            },
        )
        return ins.scalar()


def get_latest_trade_date(symbol_id: int) -> Optional[date]:
    """Checks max date across market_data_eod and market_data_history for delta sync."""
    query = text("""
        SELECT MAX(date) FROM (
            SELECT MAX(date) AS date FROM market_data_eod WHERE symbol_id = :sid
            UNION ALL
            SELECT MAX(date) AS date FROM market_data_history WHERE symbol_id = :sid
        ) t;
    """)
    with engine.connect() as conn:
        return conn.execute(query, {"sid": symbol_id}).scalar()


def fetch_bars_window(
    instrument_key: str, from_date: date, to_date: date
) -> pd.DataFrame:
    """Fetches Upstox candles in chunks up to 365 days each."""
    if from_date >= to_date:
        return pd.DataFrame()

    all_chunks = []
    curr_to = to_date

    while curr_to > from_date:
        curr_from = max(from_date, curr_to - timedelta(days=365))
        url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/day/{curr_to.strftime('%Y-%m-%d')}/{curr_from.strftime('%Y-%m-%d')}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {os.getenv('UPSTOX_ACCESS_TOKEN')}",
        }

        resp = upstox_adapter._execute_request_with_retry("GET", url, headers)
        if resp and resp.status_code == 200:
            candles = resp.json().get("data", {}).get("candles", [])
            if candles:
                df_chunk = pd.DataFrame(
                    candles,
                    columns=[
                        "timestamp",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "oi",
                    ],
                )
                df_chunk["date"] = pd.to_datetime(df_chunk["timestamp"]).dt.date
                df_chunk["adj_close"] = df_chunk["close"]
                df_chunk.drop(columns=["timestamp", "oi"], inplace=True)
                all_chunks.append(df_chunk)

        curr_to = curr_from - timedelta(days=1)
        time.sleep(0.08)

    if not all_chunks:
        return pd.DataFrame()

    full_df = pd.concat(all_chunks, ignore_index=True)
    full_df.drop_duplicates(subset=["date"], inplace=True)
    return full_df


def archive_older_bars():
    """Moves bars older than 365 days from market_data_eod to market_data_history."""
    cutoff_date = datetime.now().date() - timedelta(days=365)

    archive_sql = text("""
        -- 1. Copy older bars to market_data_history
        INSERT INTO market_data_history (symbol_id, date, open, high, low, close, adj_close, volume)
        SELECT symbol_id, date, open, high, low, close, adj_close, volume
        FROM market_data_eod
        WHERE date < :cutoff
        ON CONFLICT (symbol_id, date) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            adj_close = EXCLUDED.adj_close,
            volume = EXCLUDED.volume;

        -- 2. Delete from market_data_eod
        DELETE FROM market_data_eod WHERE date < :cutoff;
    """)

    with engine.begin() as conn:
        conn.execute(archive_sql, {"cutoff": cutoff_date})
        logger.info(
            f"📦 Archived market_data_eod bars older than {cutoff_date} into market_data_history."
        )


def ingest_stock_bars(
    symbol: str,
    is_index: bool = False,
    full_seed_years: int = 4,
    exchange_code: str = "NSE",
) -> int:
    """
    Ingests 4-year history or daily delta for a symbol using the ERD schema.
    """
    symbol_id = get_or_create_symbol_id(
        symbol, is_index=is_index, exchange_code=exchange_code
    )

    # Get instrument key
    if is_index:
        indices = {"NIFTY 50": "NSE_INDEX|Nifty 50", "NIFTY 500": "NSE_INDEX|Nifty 500"}
        instrument_key = indices.get(symbol.upper())
    else:
        instrument_key = upstox_instruments.get_instrument_key(symbol)

    if not instrument_key:
        logger.warning(f"No instrument key found for {symbol}")
        return 0

    latest_date = get_latest_trade_date(symbol_id)
    today = datetime.now().date()

    if latest_date is None:
        from_date = today - timedelta(days=full_seed_years * 365)
        logger.info(
            f"Seeding full {full_seed_years}-year data for {symbol} ({from_date} to {today})..."
        )
    else:
        from_date = latest_date + timedelta(days=1)
        if from_date >= today:
            logger.info(f"⚡ {symbol} is already up to date (Latest: {latest_date}).")
            return 0
        logger.info(f"🔄 Delta syncing {symbol} from {from_date} to {today}...")

    df = fetch_bars_window(
        instrument_key=instrument_key, from_date=from_date, to_date=today
    )
    if df.empty:
        return 0

    df["symbol_id"] = symbol_id
    cutoff_date = today - timedelta(days=365)

    eod_df = df[df["date"] >= cutoff_date]
    hist_df = df[df["date"] < cutoff_date]

    # Insert into market_data_eod (Hot Tier)
    if not eod_df.empty:
        upsert_eod = text("""
            INSERT INTO market_data_eod (symbol_id, date, open, high, low, close, adj_close, volume)
            VALUES (:symbol_id, :date, :open, :high, :low, :close, :adj_close, :volume)
            ON CONFLICT (symbol_id, date) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, adj_close = EXCLUDED.adj_close, volume = EXCLUDED.volume;
        """)
        with engine.begin() as conn:
            conn.execute(upsert_eod, eod_df.to_dict(orient="records"))

    # Insert into market_data_history (Cold Tier)
    if not hist_df.empty:
        upsert_hist = text("""
            INSERT INTO market_data_history (symbol_id, date, open, high, low, close, adj_close, volume)
            VALUES (:symbol_id, :date, :open, :high, :low, :close, :adj_close, :volume)
            ON CONFLICT (symbol_id, date) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, adj_close = EXCLUDED.adj_close, volume = EXCLUDED.volume;
        """)
        with engine.begin() as conn:
            conn.execute(upsert_hist, hist_df.to_dict(orient="records"))

    logger.info(
        f"✅ Ingested {len(df)} bars for {symbol} ({len(eod_df)} in eod, {len(hist_df)} in history)."
    )
    return len(df)


def run_eod_pipeline(symbols: list[str]):
    """Daily pipeline for benchmarks and stock list."""
    # Benchmarks
    ingest_stock_bars("NIFTY 50", is_index=True)
    ingest_stock_bars("NIFTY 500", is_index=True)

    # Stocks
    for sym in symbols:
        ingest_stock_bars(sym, is_index=False)

    # Archive > 365 days
    archive_older_bars()


if __name__ == "__main__":
    test_symbols = [
        "TRENT",
        "BEL",
        "RELIANCE",
        "COFORGE",
        "POLYCAB",
        "SOLARINDS",
        "TATAMOTORS",
    ]
    run_eod_pipeline(test_symbols)
