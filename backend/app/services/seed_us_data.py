import asyncio
import logging
import os
import time
from datetime import datetime, timedelta

import pandas as pd
from app.services.ingest_data import get_or_create_symbol_id
from dotenv import load_dotenv
from ib_insync import IB, Stock, util
from sqlalchemy import create_engine, text

load_dotenv()
logger = logging.getLogger("seed_us_data")

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url)

US_IBKR_UNIVERSE = [
    {"symbol": "SPY", "exchange": "SMART", "currency": "USD"},
    {"symbol": "QQQ", "exchange": "SMART", "currency": "USD"},
    {"symbol": "SCHD", "exchange": "SMART", "currency": "USD"},
    {"symbol": "SMH", "exchange": "SMART", "currency": "USD"},
    {"symbol": "VWRA", "exchange": "LSEETF", "currency": "USD"},
    {"symbol": "IB01", "exchange": "LSEETF", "currency": "USD"},
    {"symbol": "FUSA", "exchange": "LSEETF", "currency": "USD"},
    {"symbol": "IGLN", "exchange": "LSEETF", "currency": "USD"},
    {"symbol": "XIU", "exchange": "TSE", "currency": "CAD"},
]


def fetch_ibkr_historical_bars(
    ib: IB, contract_def: dict, duration_str: str = "4 Y"
) -> pd.DataFrame:
    contract = Stock(
        symbol=contract_def["symbol"],
        exchange=contract_def["exchange"],
        currency=contract_def["currency"],
    )

    qualified = ib.qualifyContracts(contract)
    if not qualified:
        logger.warning(f"Could not qualify contract: {contract_def}")
        return pd.DataFrame()

    bars = ib.reqHistoricalData(
        contract=contract,
        endDateTime="",
        durationStr=duration_str,
        barSizeSetting="1 day",
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
    )

    if not bars:
        return pd.DataFrame()

    df = util.df(bars)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def _run_ibkr_sync_internal(
    host: str = "127.0.0.1", port: int = 7497, client_id: int = 2
):
    """Core synchronization logic running within an active event loop."""
    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, timeout=10)
        logger.info(f"🔌 Connected to IBKR on {host}:{port}")
    except Exception as e:
        logger.error(f"❌ Failed to connect to IBKR TWS/Gateway: {e}")
        return

    today = datetime.now().date()
    cutoff_date = today - timedelta(days=365)

    try:
        for item in US_IBKR_UNIVERSE:
            sym = item["symbol"]
            exchange_code = item["exchange"]
            logger.info(f"📥 Requesting historical data from IBKR for {sym}...")

            symbol_id = get_or_create_symbol_id(
                sym, is_index=False, exchange_code=exchange_code
            )
            df = fetch_ibkr_historical_bars(ib, item, duration_str="4 Y")

            if df.empty:
                logger.warning(f"⚠️ No bars returned from IBKR for {sym}")
                continue

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

            logger.info(
                f"✅ Ingested {sym} from IBKR: {len(eod_records)} hot, {len(hist_records)} cold."
            )
            time.sleep(1.5)

    finally:
        ib.disconnect()
        logger.info("🔌 Disconnected from IBKR session.")


def seed_ibkr_universe(host: str = "127.0.0.1", port: int = 7497, client_id: int = 2):
    """
    Ensures a clean asyncio event loop exists in worker threads
    spawned by FastAPI BackgroundTasks / AnyIO.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        _run_ibkr_sync_internal(host=host, port=port, client_id=client_id)
    finally:
        loop.close()


if __name__ == "__main__":
    seed_ibkr_universe()
