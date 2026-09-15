import logging
import os
import time
from datetime import datetime, timezone
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
        csv_path = "data/selected_stocks.csv"

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

                delta = now_utc - latest_ts
                days_missing = delta.days

                # If last bar is within the last 4 hours, it is already current
                if days_missing == 0 and delta.total_seconds() < 14400:
                    skipped_count += 1
                    logger.info(
                        f"[{idx}/{len(symbols)}] ⚡ {sym} is already up to date (Latest: {latest_ts})."
                    )
                    continue

                # Fetch only missing days plus 1 buffer day for candle reconciliation
                fetch_days = min(max(days_missing + 1, 2), lookback)
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


if __name__ == "__main__":
    run_15min_ingestion_pipeline()
