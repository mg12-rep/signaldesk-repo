import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from app.services.brokers.ibkr_adapter import ibkr_adapter
from sqlalchemy import create_engine, text

logger = logging.getLogger("ingest_us_5min")

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url, pool_size=5, max_overflow=5)


def run_us_5min_ingestion_pipeline(
    csv_path: Optional[str] = None,
    days: int = 60,
    delay_seconds: float = 1.5,
):
    """
    Reads a CSV of pre-selected US tickers, fetches 5-minute bars using a single persistent
    IBKR connection, and bulk-upserts into market_data_eod_5min.
    """
    if not csv_path:
        csv_path = "C:/work/signaldesk/data/elder_input_us_stocks.csv"

    file_path = Path(csv_path)
    if not file_path.exists():
        logger.error(f"US ticker file {csv_path} not found.")
        return

    df_tickers = pd.read_csv(file_path)
    ticker_col = None
    for candidate in ["ticker", "Symbol", "symbol", "TradingSymbol"]:
        if candidate in df_tickers.columns:
            ticker_col = candidate
            break
    if not ticker_col:
        ticker_col = df_tickers.columns[0]

    tickers = (
        df_tickers[ticker_col]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
    )

    if not tickers:
        logger.warning(f"No tickers found in {csv_path}.")
        return

    logger.info(
        f"🚀 Starting US 5-minute persistent batch sync for {len(tickers)} symbols ({days}d)..."
    )

    # 1. Fetch 5-minute bars in a single persistent TWS session
    all_bars = ibkr_adapter.fetch_multiple_5min_bars(
        symbols=tickers,
        days=days,
        delay_seconds=delay_seconds,
    )

    upsert_stmt = text("""
        INSERT INTO market_data_eod_5min (symbol_id, ts, open, high, low, close, volume)
        VALUES (:symbol_id, :ts, :open, :high, :low, :close, :volume)
        ON CONFLICT (symbol_id, ts) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume;
    """)

    success_count = 0
    failed_count = 0

    with engine.connect() as conn:
        for sym, df_bars in all_bars.items():
            if df_bars.empty:
                failed_count += 1
                continue

            row = (
                conn.execute(
                    text(
                        "SELECT id FROM symbols WHERE UPPER(trading_symbol) = :sym LIMIT 1;"
                    ),
                    {"sym": sym},
                )
                .mappings()
                .first()
            )

            if not row:
                logger.warning(
                    f"Symbol {sym} not found in symbols table. Skipping DB persist."
                )
                failed_count += 1
                continue

            symbol_id = row["id"]
            df_bars["symbol_id"] = symbol_id
            records = df_bars.to_dict(orient="records")

            with engine.begin() as write_conn:
                write_conn.execute(upsert_stmt, records)

            success_count += 1
            logger.info(f"✅ {sym}: Persisted {len(records)} 5m bars to DB.")

    logger.info(
        f"🎉 US 5-min sync complete: {success_count} persisted, {failed_count} failed out of {len(tickers)}."
    )


def sync_specific_us_symbols_5min(symbols: List[str], lookback_days: int = 2) -> dict:
    """
    Fast-syncs recent 5m intraday bars for specific US tickers via IBKR.
    """
    cleaned_symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not cleaned_symbols:
        return {"synced": 0, "failed": 0, "skipped": 0}

    logger.info(f"🚀 Starting fast 5m sync for {len(cleaned_symbols)} US symbols...")

    all_bars = ibkr_adapter.fetch_multiple_5min_bars(
        symbols=cleaned_symbols,
        days=lookback_days,
        delay_seconds=1.0,
    )

    upsert_stmt = text("""
        INSERT INTO market_data_eod_5min (symbol_id, ts, open, high, low, close, volume)
        VALUES (:symbol_id, :ts, :open, :high, :low, :close, :volume)
        ON CONFLICT (symbol_id, ts) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume;
    """)

    synced = 0
    failed = 0
    skipped = 0

    with engine.connect() as conn:
        for sym in cleaned_symbols:
            df_bars = all_bars.get(sym)
            if df_bars is None or df_bars.empty:
                logger.warning(f"No bars returned for {sym}")
                failed += 1
                continue

            row = (
                conn.execute(
                    text(
                        "SELECT id FROM symbols WHERE UPPER(trading_symbol) = :sym LIMIT 1;"
                    ),
                    {"sym": sym},
                )
                .mappings()
                .first()
            )

            if not row:
                logger.warning(f"Symbol {sym} not in symbols table.")
                failed += 1
                continue

            symbol_id = row["id"]

            latest_ts = conn.execute(
                text(
                    "SELECT MAX(ts) FROM market_data_eod_5min WHERE symbol_id = :sid;"
                ),
                {"sid": symbol_id},
            ).scalar()

            if latest_ts is not None:
                if latest_ts.tzinfo is None:
                    latest_ts = latest_ts.replace(tzinfo=timezone.utc)
                df_bars = df_bars[df_bars["ts"] >= latest_ts]

            if df_bars.empty:
                skipped += 1
                continue

            df_bars["symbol_id"] = symbol_id
            records = df_bars.to_dict(orient="records")

            with engine.begin() as write_conn:
                write_conn.execute(upsert_stmt, records)

            synced += 1
            logger.info(f"✅ {sym}: Fast-synced {len(records)} 5m bars.")

    return {"synced": synced, "failed": failed, "skipped": skipped}


# Backward compatibility aliases
run_us_15min_ingestion_pipeline = run_us_5min_ingestion_pipeline
sync_specific_us_symbols_15min = sync_specific_us_symbols_5min

if __name__ == "__main__":
    run_us_5min_ingestion_pipeline()
