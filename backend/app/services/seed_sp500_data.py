import asyncio
import io
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import requests
from app.services.ingest_market_data import get_or_create_symbol_id
from dotenv import load_dotenv
from ib_insync import IB, Stock, util
from sqlalchemy import create_engine, text

load_dotenv()
logger = logging.getLogger("seed_sp500")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url)


def get_sp500_symbols() -> List[Dict[str, str]]:
    """
    Fetches official S&P 500 constituent table from Wikipedia / DataHub.
    Normalizes dots to spaces for IBKR (e.g. BRK.B -> BRK B).
    """
    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            df = pd.read_csv(io.StringIO(resp.text))
            symbols_list = []
            for _, row in df.iterrows():
                raw_sym = str(row["Symbol"]).strip()
                # IBKR uses spaces instead of dots for class shares
                ibkr_sym = raw_sym.replace(".", " ")
                symbols_list.append(
                    {
                        "raw_symbol": raw_sym,
                        "ibkr_symbol": ibkr_sym,
                        "name": str(row.get("Name", raw_sym)),
                        "sector": str(row.get("Sector", "Equities")),
                    }
                )
            logger.info(f"Loaded {len(symbols_list)} S&P 500 constituents.")
            return symbols_list
    except Exception as e:
        logger.warning(
            f"Could not fetch dynamic S&P 500 list ({e}). Using top mega-cap fallback."
        )

    # Fallback list
    fallback = [
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "TSLA",
        "BRK B",
        "JPM",
        "V",
        "UNH",
        "XOM",
        "LLY",
    ]
    return [
        {
            "raw_symbol": s.replace(" ", "."),
            "ibkr_symbol": s,
            "name": s,
            "sector": "Equities",
        }
        for s in fallback
    ]


def get_latest_trade_date(symbol_id: int) -> Optional[date]:
    """Checks max date across market_data_eod and market_data_history."""
    query = text("""
        SELECT MAX(date) FROM (
            SELECT MAX(date) AS date FROM market_data_eod WHERE symbol_id = :sid
            UNION ALL
            SELECT MAX(date) AS date FROM market_data_history WHERE symbol_id = :sid
        ) t;
    """)
    with engine.connect() as conn:
        return conn.execute(query, {"sid": symbol_id}).scalar()


def fetch_historical_bars_with_retry(
    ib: IB, ibkr_symbol: str, duration_str: str = "4 Y", max_retries: int = 3
) -> pd.DataFrame:
    """Requests historical daily bars from TWS with rate-limit backoff."""
    contract = Stock(symbol=ibkr_symbol, exchange="SMART", currency="USD")
    qualified = ib.qualifyContracts(contract)

    if not qualified:
        logger.warning(f"⚠️ Could not qualify contract for: {ibkr_symbol}")
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
            if "pacing violation" in str(e).lower():
                wait_time = attempt * 10
                logger.warning(
                    f"⏳ Pacing violation on {ibkr_symbol}. Backing off for {wait_time}s (Attempt {attempt}/{max_retries})..."
                )
                time.sleep(wait_time)
            else:
                logger.error(f"Error fetching {ibkr_symbol}: {e}")
                break

    return pd.DataFrame()


def _run_sp500_sync_internal(
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 2,
    max_symbols: Optional[int] = None,
):
    """Executes the S&P 500 ingestion loop."""
    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, timeout=10)
        logger.info(f"🔌 Connected to IBKR TWS on {host}:{port}")
    except Exception as e:
        logger.error(f"❌ Failed to connect to IBKR TWS: {e}. Ensure TWS is running.")
        return

    today = datetime.now().date()
    cutoff_date = today - timedelta(days=365)

    # 1. Ingest S&P 500 Benchmark Index / ETF
    benchmarks = [{"symbol": "SPY", "exchange": "SMART", "currency": "USD"}]
    for bench in benchmarks:
        sym = bench["symbol"]
        symbol_id = get_or_create_symbol_id(sym, is_index=True, exchange_code="US")
        df_bench = fetch_historical_bars_with_retry(ib, sym, duration_str="4 Y")
        if not df_bench.empty:
            _persist_bars(df_bench, symbol_id, cutoff_date)
            logger.info(f"✅ Ingested Benchmark: {sym}")
        time.sleep(1.5)

    # 2. Ingest S&P 500 Stock Universe
    universe = get_sp500_symbols()
    if max_symbols:
        universe = universe[:max_symbols]

    total = len(universe)
    logger.info(f"🚀 Ingesting {total} S&P 500 equities...")

    success = 0
    skipped = 0
    failed = 0

    try:
        for idx, item in enumerate(universe, 1):
            raw_sym = item["raw_symbol"]
            ibkr_sym = item["ibkr_symbol"]

            try:
                symbol_id = get_or_create_symbol_id(
                    raw_sym, is_index=False, exchange_code="US"
                )
                latest_date = get_latest_trade_date(symbol_id)

                if latest_date and latest_date >= today:
                    skipped += 1
                    continue

                duration = (
                    "4 Y"
                    if latest_date is None
                    else f"{(today - latest_date).days + 2} D"
                )
                df = fetch_historical_bars_with_retry(
                    ib, ibkr_sym, duration_str=duration
                )

                if df.empty:
                    failed += 1
                    logger.warning(f"[{idx}/{total}] No data for {raw_sym}")
                    continue

                _persist_bars(df, symbol_id, cutoff_date)
                success += 1
                logger.info(f"[{idx}/{total}] ✅ {raw_sym} ({len(df)} bars)")

            except Exception as e:
                failed += 1
                logger.error(f"[{idx}/{total}] ❌ Failed {raw_sym}: {e}")

            # Pacing delay between stock requests
            time.sleep(1.2)

    finally:
        ib.disconnect()
        logger.info(
            f"🎉 S&P 500 Sync Complete: {success} updated, {skipped} up-to-date, {failed} failed."
        )


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


def seed_sp500_universe(
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 2,
    max_symbols: Optional[int] = None,
):
    """Thread-safe entry point for FastAPI BackgroundTasks and CLI."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        _run_sp500_sync_internal(
            host=host, port=port, client_id=client_id, max_symbols=max_symbols
        )
    finally:
        loop.close()


if __name__ == "__main__":
    # Test run: sync first 10 symbols (or remove max_symbols for all 503)
    seed_sp500_universe(max_symbols=10)
