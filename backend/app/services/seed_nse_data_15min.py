import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from app.services.brokers.upstox_adapter import upstox_adapter
from app.services.upstox_instruments import upstox_instruments
from sqlalchemy import create_engine, text

logger = logging.getLogger("ingest_15min_data")

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url, pool_size=5, max_overflow=5)

IST_OFFSET = timezone(timedelta(hours=5, minutes=30))


def run_15min_ingestion_pipeline(
    csv_path: Optional[str] = None,
    days: int = 90,
    default_lookback_days: Optional[int] = None,
):
    """
    Reads pre-selected NSE symbols from CSV and syncs 15-minute bars.
    Automatically switches between a full seed and a delta fetch based on DB state.
    Accepts both 'days' and 'default_lookback_days' to prevent parameter mismatch.
    """
    lookback = default_lookback_days if default_lookback_days is not None else days

    if not csv_path:
        csv_path = "data/elder_input_us_stocks.csv"

    file_path = Path(csv_path)
    if not file_path.exists():
        logger.error(f"Selected stocks file not found at: {file_path}")
        return

    df_csv = pd.read_csv(file_path)
    symbol_col = None
    for candidate in [
        "symbol",
        "trading_symbol",
        "Symbol",
        "TradingSymbol",
        "Ticker",
        "ticker",
    ]:
        if candidate in df_csv.columns:
            symbol_col = candidate
            break
    if not symbol_col:
        symbol_col = df_csv.columns[0]

    symbols = (
        df_csv[symbol_col]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
    )

    logger.info(f"🚀 Starting 15-minute delta sync for {len(symbols)} symbols...")

    upsert_stmt = text("""
        INSERT INTO market_data_eod_15min (symbol_id, ts, open, high, low, close, volume)
        VALUES (:symbol_id, :ts, :open, :high, :low, :close, :volume)
        ON CONFLICT (symbol_id, ts) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume;
    """)

    success_count = 0
    skipped_count = 0
    failed_count = 0
    now_utc = datetime.now(timezone.utc)
    today_ist_date = now_utc.astimezone(IST_OFFSET).date()

    with engine.connect() as conn:
        for idx, sym in enumerate(symbols, start=1):
            # 1. Resolve symbol ID
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
                    f"[{idx}/{len(symbols)}] ⚠️ Symbol '{sym}' not in symbols table. Skipping."
                )
                failed_count += 1
                continue

            symbol_id = row["id"]

            # 2. Inspect latest available timestamp in DB for delta calculation
            latest_ts = conn.execute(
                text(
                    "SELECT MAX(ts) FROM market_data_eod_15min WHERE symbol_id = :sid;"
                ),
                {"sid": symbol_id},
            ).scalar()

            if latest_ts is None:
                fetch_days = lookback
                logger.info(
                    f"[{idx}/{len(symbols)}] Seeding initial {fetch_days}d for {sym}..."
                )
            else:
                # Ensure latest_ts is timezone-aware UTC
                if latest_ts.tzinfo is None:
                    latest_ts = latest_ts.replace(tzinfo=timezone.utc)

                latest_ist = latest_ts.astimezone(IST_OFFSET)
                latest_ist_date = latest_ist.date()

                # If we already have today's final closing bar (09:45 UTC / 15:15 IST), skip
                if (
                    latest_ist_date == today_ist_date
                    and latest_ist.time().hour >= 15
                    and latest_ist.time().minute >= 15
                ):
                    skipped_count += 1
                    logger.info(
                        f"[{idx}/{len(symbols)}] ⚡ {sym} is already up to date for today ({latest_ts})."
                    )
                    continue

                # Fetch missing calendar days plus 1 buffer day for reconciliation
                calendar_days_missing = (today_ist_date - latest_ist_date).days
                fetch_days = min(max(calendar_days_missing + 1, 2), lookback)
                logger.info(
                    f"[{idx}/{len(symbols)}] 🔄 Delta fetching {fetch_days}d for {sym} (Latest: {latest_ts})..."
                )

            # 3. Resolve instrument key
            instrument_key = upstox_instruments.get_instrument_key(sym)
            if not instrument_key:
                logger.warning(
                    f"[{idx}/{len(symbols)}] ⚠️ No Upstox key found for {sym}"
                )
                failed_count += 1
                continue

            try:
                # 4. Fetch candles for calculated window
                df_bars = upstox_adapter.fetch_historical_candles(
                    instrument_key=instrument_key,
                    interval="15minute",
                    days=fetch_days,
                )

                if df_bars.empty:
                    logger.warning(
                        f"[{idx}/{len(symbols)}] ⚠️ No 15m data returned for {sym}"
                    )
                    failed_count += 1
                    continue

                # Filter only new or updated bars if latest_ts exists
                if latest_ts is not None:
                    df_bars = df_bars[df_bars["ts"] >= latest_ts]

                if df_bars.empty:
                    skipped_count += 1
                    continue

                df_bars["symbol_id"] = symbol_id
                records = df_bars.to_dict(orient="records")

                # 5. Persist
                with engine.begin() as write_conn:
                    write_conn.execute(upsert_stmt, records)

                success_count += 1
                logger.info(
                    f"[{idx}/{len(symbols)}] ✅ {sym}: Synced {len(records)} bars."
                )

            except Exception as e:
                failed_count += 1
                logger.error(f"[{idx}/{len(symbols)}] ❌ Error syncing {sym}: {e}")

            time.sleep(0.3)

    logger.info(
        f"🎉 15m Sync Complete: {success_count} synced, {skipped_count} up-to-date, {failed_count} failed out of {len(symbols)}."
    )


def sync_specific_symbols_15min(symbols: list[str]) -> dict:
    """
    Fast-syncs 15m intraday bars only for the specified list of symbols.
    Pulls today's intraday bars and delta-upserts into market_data_eod_15min.
    """
    cleaned_symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not cleaned_symbols:
        return {"synced": 0, "failed": 0, "skipped": 0}

    upsert_stmt = text("""
        INSERT INTO market_data_eod_15min (symbol_id, ts, open, high, low, close, volume)
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
            # 1. Get symbol ID
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
                failed += 1
                continue

            symbol_id = row["id"]

            # 2. Get latest timestamp
            latest_ts = conn.execute(
                text(
                    "SELECT MAX(ts) FROM market_data_eod_15min WHERE symbol_id = :sid;"
                ),
                {"sid": symbol_id},
            ).scalar()

            # 3. Resolve instrument key
            instrument_key = upstox_instruments.get_instrument_key(sym)
            if not instrument_key:
                failed += 1
                continue

            try:
                # 4. Fetch delta (default 2 days covers today + yesterday's reconciliation)
                df_bars = upstox_adapter.fetch_historical_candles(
                    instrument_key=instrument_key,
                    interval="15minute",
                    days=2,
                )

                if df_bars.empty:
                    skipped += 1
                    continue

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
            except Exception as e:
                logger.error(f"Error fast-syncing {sym}: {e}")
                failed += 1

            time.sleep(0.15)

    return {"synced": synced, "failed": failed, "skipped": skipped}


if __name__ == "__main__":
    run_15min_ingestion_pipeline()
