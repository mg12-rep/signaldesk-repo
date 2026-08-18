import asyncio
import io
from datetime import date, timedelta

import pandas as pd
import requests
from app.db.models import Exchange, MarketDataEOD, Symbol
from app.db.session import AsyncSessionLocal
from requests.adapters import HTTPAdapter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from urllib3.util import Retry

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.nseindia.com/",
    "Origin": "https://www.nseindia.com",
    "Accept": "text/csv,*/*",
}


def get_nse_session() -> requests.Session:
    """Creates a resilient requests Session with NSE warm-up cookies."""
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(HEADERS)
    try:
        session.get("https://www.nseindia.com", timeout=10)
    except Exception:
        pass
    return session


async def patch_recent_eod():
    print("🚀 Starting NSE Direct Bhavcopy Backfill for `market_data_eod`...\n")

    # 1. Load DB symbols map (trading_symbol -> symbol_id)
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Symbol.trading_symbol, Symbol.id)
            .join(Exchange)
            .where(Exchange.code == "NSE", Symbol.is_active == True)
        )
        res = await session.execute(stmt)
        symbol_map = {str(row[0]).strip().upper(): row[1] for row in res.all()}

    print(f"📌 Active NSE Symbols loaded from DB: {len(symbol_map)}")

    # 2. Date Range Setup (Last 2 Years for Hot Storage)
    end_date = date.today()
    start_date = end_date - timedelta(days=2 * 365)
    print(f"📅 Fetching dates: {start_date} to {end_date}\n")

    http_session = get_nse_session()
    current_date = start_date
    total_records = 0

    while current_date <= end_date:
        # Skip weekends
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue

        date_str = current_date.strftime("%d%m%Y")
        url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"

        try:
            resp = http_session.get(url, timeout=15)

            if resp.status_code == 404:
                current_date += timedelta(days=1)
                continue

            resp.raise_for_status()

            # Parse CSV from memory
            df = pd.read_csv(io.StringIO(resp.text))
            
            # Clean all column names by stripping whitespace and converting to uppercase
            df.columns = [str(c).strip().upper() for c in df.columns]

            # Determine column names dynamically
            symbol_col = next((c for c in df.columns if "SYMBOL" in c), None)
            series_col = next((c for c in df.columns if "SERIES" in c), None)
            open_col = next((c for c in df.columns if "OPEN" in c), None)
            high_col = next((c for c in df.columns if "HIGH" in c), None)
            low_col = next((c for c in df.columns if "LOW" in c), None)
            close_col = next((c for c in df.columns if "CLOSE" in c), None)
            qty_col = next((c for c in df.columns if "TTL_TRD_QNT" in c or "TRADED_QTY" in c or "QTY" in c or "VOLUME" in c), None)

            if not symbol_col or not close_col:
                print(f"  [{current_date}] Skipping: essential columns missing.")
                current_date += timedelta(days=1)
                continue

            records = []
            for _, row in df.iterrows():
                # Filter series if available
                if series_col and pd.notna(row[series_col]):
                    ser = str(row[series_col]).strip().upper()
                    if ser not in ["EQ", "BE"]:
                        continue

                sym = str(row[symbol_col]).strip().upper()
                if sym in symbol_map:
                    try:
                        open_val = float(str(row[open_col]).strip()) if open_col and pd.notna(row[open_col]) else 0.0
                        high_val = float(str(row[high_col]).strip()) if high_col and pd.notna(row[high_col]) else 0.0
                        low_val = float(str(row[low_col]).strip()) if low_col and pd.notna(row[low_col]) else 0.0
                        close_val = float(str(row[close_col]).strip()) if pd.notna(row[close_col]) else 0.0
                        qty_val = int(float(str(row[qty_col]).strip())) if qty_col and pd.notna(row[qty_col]) else 0

                        if close_val > 0:
                            records.append({
                                "symbol_id": symbol_map[sym],
                                "date": current_date,
                                "open": open_val if open_val > 0 else close_val,
                                "high": high_val if high_val > 0 else close_val,
                                "low": low_val if low_val > 0 else close_val,
                                "close": close_val,
                                "adj_close": close_val,
                                "volume": qty_val,
                            })
                    except (ValueError, KeyError):
                        continue

            if records:
                async with AsyncSessionLocal() as session:
                    stmt = insert(MarketDataEOD).values(records)
                    stmt = stmt.on_conflict_do_nothing()
                    await session.execute(stmt)
                    await session.commit()
                    total_records += len(records)
                    print(f"✅ [{current_date}] Inserted {len(records)} candles.")

        except Exception as e:
            print(f"  [{current_date}] Error: {e}")

        current_date += timedelta(days=1)

    print(f"\n🎉 `market_data_eod` Backfill Complete! Total candles inserted: {total_records}")


if __name__ == "__main__":
    asyncio.run(patch_recent_eod())