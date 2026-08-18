import asyncio
import io
import zipfile
from datetime import date, timedelta

import pandas as pd
import requests
from app.db.models import Exchange, MarketDataEOD, Symbol
from app.db.session import AsyncSessionLocal
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def get_bhavcopy_url(target_date: date) -> str:
    dd = target_date.strftime("%d")
    mmm = target_date.strftime("%b").upper()
    yyyy = target_date.strftime("%Y")
    return f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip"


async def fetch_and_upsert_daily(target_date: date, symbol_map: dict[str, int]) -> int:
    if target_date.weekday() >= 5:
        return 0  # Weekend

    url = get_bhavcopy_url(target_date)
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"ℹ️ [{target_date}] No Bhavcopy available (HTTP {resp.status_code}). Likely a market holiday.")
            return 0

        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            csv_filename = z.namelist()[0]
            with z.open(csv_filename) as f:
                df = pd.read_csv(f)

        df.columns = [c.strip().upper() for c in df.columns]
        if "SERIES" in df.columns:
            df = df[df["SERIES"].isin(["EQ", "BE"])]

        records = []
        for _, row in df.iterrows():
            sym = str(row["SYMBOL"]).strip()
            if sym in symbol_map:
                records.append({
                    "symbol_id": symbol_map[sym],
                    "date": target_date,
                    "open": float(row["OPEN"]),
                    "high": float(row["HIGH"]),
                    "low": float(row["LOW"]),
                    "close": float(row["CLOSE"]),
                    "adj_close": float(row["CLOSE"]),
                    "volume": int(row["TOTTRDQTY"] if "TOTTRDQTY" in row else row["TOTALTRADES"]),
                })

        if not records:
            return 0

        async with AsyncSessionLocal() as session:
            stmt = insert(MarketDataEOD).values(records)
            stmt = stmt.on_conflict_do_update(
                constraint="_symbol_date_eod_uc",
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "adj_close": stmt.excluded.adj_close,
                    "volume": stmt.excluded.volume,
                },
            )
            await session.execute(stmt)
            await session.commit()

        print(f"✅ [{target_date}] Upserted {len(records)} candles into `market_data_eod`.")
        return len(records)

    except Exception as e:
        print(f"❌ [{target_date}] Failed to ingest: {e}")
        return 0


async def run_daily_ingest():
    print("🚀 Running Daily NSE Incremental Ingestion...")

    async with AsyncSessionLocal() as session:
        # Load symbol lookup map
        stmt = select(Symbol.trading_symbol, Symbol.id).join(Exchange).where(Exchange.code == "NSE")
        res = await session.execute(stmt)
        symbol_map = {row[0]: row[1] for row in res.all()}

        # Find latest date in market_data_eod to handle missing days / gap recovery
        stmt_max = select(func.max(MarketDataEOD.date))
        max_date_res = await session.execute(stmt_max)
        latest_db_date = max_date_res.scalar()

    today = date.today()
    start_date = (latest_db_date + timedelta(days=1)) if latest_db_date else today

    if start_date > today:
        print("✅ Market data is already up to date!")
        return

    print(f"🔎 Catching up daily data from {start_date} to {today}...")

    curr = start_date
    while curr <= today:
        await fetch_and_upsert_daily(curr, symbol_map)
        curr += timedelta(days=1)

    print("🎉 Daily Incremental Ingest Complete!")


if __name__ == "__main__":
    asyncio.run(run_daily_ingest())