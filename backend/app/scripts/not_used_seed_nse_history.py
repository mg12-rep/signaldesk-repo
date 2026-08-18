import asyncio
import io
import zipfile
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from app.db.models import Exchange, MarketDataEOD, MarketDataHistory, Symbol
from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def get_bhavcopy_url(target_date: date) -> str:
    """NSE Archival Bhavcopy URL pattern (full format changed to UDIC format in recent years)."""
    dd = target_date.strftime("%d")
    mmm = target_date.strftime("%b").upper()
    yyyy = target_date.strftime("%Y")
    mm = target_date.strftime("%m")
    
    # Standard format: https://archives.nseindia.com/content/historical/EQUITIES/2024/JAN/cm15JAN2024bhav.csv.zip
    return f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip"


async def process_date(target_date: date, symbol_map: dict[str, int], cutoff_date: date) -> tuple[int, str]:
    if target_date.weekday() >= 5:  # Skip Saturday/Sunday
        return 0, "Weekend"

    url = get_bhavcopy_url(target_date)
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 404:
            return 0, "Holiday/No Data"
        if resp.status_code != 200:
            return 0, f"HTTP {resp.status_code}"

        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            csv_filename = z.namelist()[0]
            with z.open(csv_filename) as f:
                df = pd.read_csv(f)

        # Standardize columns
        df.columns = [c.strip().upper() for c in df.columns]
        
        # Filter EQ series and matching database symbols
        if "SERIES" in df.columns:
            df = df[df["SERIES"].isin(["EQ", "BE"])]

        records_eod = []
        records_hist = []

        for _, row in df.iterrows():
            sym = str(row["SYMBOL"]).strip()
            if sym in symbol_map:
                symbol_id = symbol_map[sym]
                
                rec = {
                    "symbol_id": symbol_id,
                    "date": target_date,
                    "open": float(row["OPEN"]),
                    "high": float(row["HIGH"]),
                    "low": float(row["LOW"]),
                    "close": float(row["CLOSE"]),
                    "adj_close": float(row["CLOSE"]),  # Bhavcopy close is unadjusted; updated via corporate action feed if required
                    "volume": int(row["TOTTRDQTY"] if "TOTTRDQTY" in row else row["TOTALTRADES"]),
                }

                if target_date < cutoff_date:
                    records_hist.append(rec)
                else:
                    records_eod.append(rec)

        async with AsyncSessionLocal() as session:
            if records_eod:
                stmt = insert(MarketDataEOD).values(records_eod)
                stmt = stmt.on_conflict_do_nothing()
                await session.execute(stmt)

            if records_hist:
                stmt = insert(MarketDataHistory).values(records_hist)
                stmt = stmt.on_conflict_do_nothing()
                await session.execute(stmt)

            await session.commit()

        return len(records_eod) + len(records_hist), "Success"

    except Exception as e:
        return 0, f"Error: {str(e)}"


async def seed_5year_history():
    print("🚀 Starting 5-Year NSE Historical Data Backfill...")
    
    async with AsyncSessionLocal() as session:
        # Load symbol lookup map
        stmt = select(Symbol.trading_symbol, Symbol.id).join(Exchange).where(Exchange.code == "NSE")
        res = await session.execute(stmt)
        symbol_map = {row[0]: row[1] for row in res.all()}
        print(f"📌 Active NSE Symbols in DB: {len(symbol_map)}")

    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=5 * 365)
    cutoff_date = end_date - timedelta(days=2 * 365)  # 2 years cutoff for Hot vs Cold split

    print(f"📅 Backfilling Range: {start_date} to {end_date}")
    print(f"🔥 Hot Data (`market_data_eod`): >= {cutoff_date}")
    print(f"❄️ Cold Data (`market_data_history`): < {cutoff_date}")

    current_date = start_date
    total_records = 0

    while current_date <= end_date:
        count, status = await process_date(current_date, symbol_map, cutoff_date)
        if count > 0:
            total_records += count
            print(f"  [{current_date}] Loaded {count} candles ({status})")
        elif status not in ["Weekend", "Holiday/No Data"]:
            print(f"  [{current_date}] Skipped: {status}")
        
        current_date += timedelta(days=1)

    print(f"🎉 5-Year Backfill Complete! Total candles inserted: {total_records}")


if __name__ == "__main__":
    asyncio.run(seed_5year_history())