import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from app.services.brokers.ibkr_adapter import ibkr_adapter
from sqlalchemy import create_engine, text

logger = logging.getLogger("ingest_us_15min")

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url, pool_size=5, max_overflow=5)


def run_us_15min_ingestion_pipeline(
    csv_path: Optional[str] = None,
    days: int = 90,
    delay_seconds: float = 1.0,
):
    """
    Reads a CSV of pre-selected US tickers, fetches 15-minute bars via IBKR,
    and upserts into market_data_eod_15min.
    """
    if not csv_path:
        csv_path = "data/selected_us_stocks.csv"

    file_path = Path(csv_path)
    if not file_path.exists():
        logger.error(f"US ticker file {csv_path} not found.")
        return

    df_tickers = pd.read_csv(file_path)
    ticker_col = "ticker" if "ticker" in df_tickers.columns else df_tickers.columns[0]
    tickers = df_tickers[ticker_col].dropna().astype(str).str.strip().unique().tolist()

    logger.info(
        f"🚀 Starting US 15-minute ingestion for {len(tickers)} symbols ({days}d)..."
    )

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
    failed_count = 0

    with engine.connect() as conn:
        for idx, ticker in enumerate(tickers, start=1):
            sym = ticker.upper()

            # Resolve symbol_id from DB
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
                    f"[{idx}/{len(tickers)}] Symbol {sym} not found in DB. Skipping."
                )
                failed_count += 1
                continue

            symbol_id = row["id"]

            # Fetch 15-minute bars
            df_bars = ibkr_adapter.fetch_15min_historical_bars(symbol=sym, days=days)
            if df_bars.empty:
                logger.warning(
                    f"[{idx}/{len(tickers)}] No 15-minute bars returned for {sym}"
                )
                failed_count += 1
                continue

            df_bars["symbol_id"] = symbol_id
            records = df_bars.to_dict(orient="records")

            with engine.begin() as write_conn:
                write_conn.execute(upsert_stmt, records)

            success_count += 1
            logger.info(
                f"[{idx}/{len(tickers)}] ✅ {sym}: Ingested {len(records)} 15-minute bars"
            )

    logger.info(
        f"🎉 US 15-min sync complete: {success_count} succeeded, {failed_count} failed."
    )
