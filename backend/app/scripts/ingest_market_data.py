import argparse
import asyncio
import io
from datetime import date, timedelta

import pandas as pd
import requests
import yfinance as yf
from app.db.models import Exchange, MarketDataEOD, MarketDataHistory, Symbol
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


async def ingest_nse(start_date: date, end_date: date, cutoff_date: date):
    print(f"📥 Starting NSE Market Ingestion ({start_date} to {end_date})...")

    async with AsyncSessionLocal() as session:
        stmt = (
            select(Symbol.trading_symbol, Symbol.id)
            .join(Exchange)
            .where(Exchange.code == "NSE", Symbol.is_active == True)
        )
        res = await session.execute(stmt)
        symbol_map = {str(row[0]).strip().upper(): row[1] for row in res.all()}

    http_session = get_nse_session()
    current_date = start_date
    total_inserted = 0

    while current_date <= end_date:
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

            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = [str(c).strip().upper() for c in df.columns]

            open_col  = next((c for c in df.columns if "OPEN" in c), None)

            symbol_col = next((c for c in df.columns if "SYMBOL" in c), None)
            series_col = next((c for c in df.columns if "SERIES" in c), None)
            open_col  = next((c for c in df.columns if c == "OPEN_PRICE" or "OPEN" in c), None)
            high_col  = next((c for c in df.columns if c == "HIGH_PRICE" or "HIGH" in c), None)
            low_col   = next((c for c in df.columns if c == "LOW_PRICE" or "LOW" in c), None)
            close_col = next((c for c in df.columns if c == "CLOSE_PRICE" or ("CLOSE" in c and "PREV" not in c)), None)
            qty_col   = next((c for c in df.columns if "TTL_TRD_QNT" in c or "TRADED_QTY" in c or "QTY" in c), None)

            records_eod = []
            records_hist = []

            for _, row in df.iterrows():
                if series_col and pd.notna(row[series_col]):
                    if str(row[series_col]).strip().upper() not in ["EQ", "BE"]:
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
                            rec = {
                                "symbol_id": symbol_map[sym],
                                "date": current_date,
                                "open": open_val if open_val > 0 else close_val,
                                "high": high_val if high_val > 0 else close_val,
                                "low": low_val if low_val > 0 else close_val,
                                "close": close_val,
                                "adj_close": close_val,
                                "volume": qty_val,
                            }
                            if current_date < cutoff_date:
                                records_hist.append(rec)
                            else:
                                records_eod.append(rec)
                    except (ValueError, KeyError):
                        continue

            async with AsyncSessionLocal() as session:
                if records_eod:
                    stmt = insert(MarketDataEOD).values(records_eod).on_conflict_do_nothing()
                    await session.execute(stmt)
                if records_hist:
                    stmt = insert(MarketDataHistory).values(records_hist).on_conflict_do_nothing()
                    await session.execute(stmt)
                await session.commit()
                total_inserted += len(records_eod) + len(records_hist)

        except Exception as e:
            print(f"  [{current_date}] Error: {e}")

        current_date += timedelta(days=1)

    print(f"✅ NSE Ingestion Complete! Inserted {total_inserted} candles.\n")


async def ingest_us(start_date: date, end_date: date, cutoff_date: date):
    print(f"📥 Starting US Market Ingestion (S&P 500) ({start_date} to {end_date})...")

    async with AsyncSessionLocal() as session:
        stmt = (
            select(Symbol.id, Symbol.trading_symbol, Symbol.yf_symbol)
            .join(Exchange)
            .where(Exchange.code.in_(["NYSE", "NASDAQ"]), Symbol.is_active == True)
        )
        res = await session.execute(stmt)
        symbols = res.all()

    print(f"📌 Loaded {len(symbols)} US symbols from DB.")

    total_inserted = 0

    for idx, sym_obj in enumerate(symbols):
        yf_sym = sym_obj.yf_symbol
        symbol_id = sym_obj.id

        if not yf_sym:
            continue

        try:
            ticker = yf.Ticker(yf_sym)
            df = ticker.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))

            if df.empty:
                continue

            records_eod = []
            records_hist = []

            for ts, row in df.iterrows():
                candle_date = ts.date() if hasattr(ts, "date") else ts
                rec = {
                    "symbol_id": symbol_id,
                    "date": candle_date,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "adj_close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                }
                if candle_date < cutoff_date:
                    records_hist.append(rec)
                else:
                    records_eod.append(rec)

            async with AsyncSessionLocal() as session:
                if records_eod:
                    stmt = insert(MarketDataEOD).values(records_eod).on_conflict_do_nothing()
                    await session.execute(stmt)
                if records_hist:
                    stmt = insert(MarketDataHistory).values(records_hist).on_conflict_do_nothing()
                    await session.execute(stmt)
                await session.commit()
                total_inserted += len(records_eod) + len(records_hist)

            if (idx + 1) % 50 == 0 or (idx + 1) == len(symbols):
                print(f"  [{idx + 1}/{len(symbols)}] Processed US symbols. Total candles: {total_inserted}")

        except Exception as e:
            continue

    print(f"✅ US Ingestion Complete! Inserted {total_inserted} total candles.\n")


async def main():
    parser = argparse.ArgumentParser(description="SignalDesk Master Market Data Ingestion Engine")
    parser.add_argument("--days", type=int, default=730, help="Number of historical days to ingest (default: 730 / 2 years)")
    parser.add_argument("--market", choices=["all", "nse", "us"], default="all", help="Market region to ingest")
    args = parser.parse_args()

    end_date = date.today()
    start_date = end_date - timedelta(days=args.days)
    # Cutoff for 1-Year Hot vs Cold storage
    cutoff_date = end_date - timedelta(days=365)

    print(f"🚀 SignalDesk Master Ingestion Engine Started")
    print(f"📅 Range: {start_date} to {end_date} (Hot/Cold Cutoff: {cutoff_date})\n")

    if args.market in ["all", "nse"]:
        await ingest_nse(start_date, end_date, cutoff_date)

    if args.market in ["all", "us"]:
        await ingest_us(start_date, end_date, cutoff_date)

    print("🎉 Master Ingestion Finished!")


if __name__ == "__main__":
    asyncio.run(main())