import asyncio
from datetime import datetime, timedelta

import pandas as pd
from nselib import capital_market
from sqlalchemy import inspect, select

from backend.app.db.models import MarketDataEOD, Symbol
from backend.app.db.session import AsyncSessionLocal

# Target Nifty liquid tickers
TARGET_SYMBOLS = [
    {"ticker": "RELIANCE", "name": "Reliance Industries Ltd", "token": 738561},
    {"ticker": "TCS", "name": "Tata Consultancy Services Ltd", "token": 2953217},
    {"ticker": "INFY", "name": "Infosys Ltd", "token": 408065},
    {"ticker": "HDFCBANK", "name": "HDFC Bank Ltd", "token": 341249},
    {"ticker": "ICICIBANK", "name": "ICICI Bank Ltd", "token": 1270529},
    {"ticker": "TATAMOTORS", "name": "Tata Motors Ltd", "token": 884737},
    {"ticker": "SBIN", "name": "State Bank of India", "token": 779521},
]

def get_eod_date_attr():
    """Detects date attribute on MarketDataEOD model."""
    mapper = inspect(MarketDataEOD)
    cols = [column.key for column in mapper.attrs]
    for possible in ["date", "timestamp", "trading_date", "datetime"]:
        if possible in cols:
            return possible
    raise AttributeError(f"MarketDataEOD columns found: {cols}. Expected date attribute.")

async def seed_symbols_and_history():
    date_attr = get_eod_date_attr()
    print(f"🔍 Detected '{date_attr}' attribute on MarketDataEOD model.")

    async with AsyncSessionLocal() as session:
        print("🌱 Seeding symbols into database...")
        symbol_map = {}

        # 1. Upsert Symbols catalog
        for idx, item in enumerate(TARGET_SYMBOLS, start=1001):
            stmt = select(Symbol).where(Symbol.trading_symbol == item["ticker"])
            result = await session.execute(stmt)
            existing_symbol = result.scalar_one_or_none()

            if not existing_symbol:
                token = item.get("token", idx)
                new_symbol = Symbol(
                    trading_symbol=item["ticker"],
                    instrument_token=token,
                    exchange="NSE",
                    is_active=True
                )
                session.add(new_symbol)
                await session.flush()
                symbol_map[item["ticker"]] = new_symbol.id
            else:
                symbol_map[item["ticker"]] = existing_symbol.id

        await session.commit()
        print("✅ Symbols catalog updated!")

        # 2. Date range for 1 Year of historical data
        to_date = datetime.now().strftime("%d-%m-%Y")
        from_date = (datetime.now() - timedelta(days=365)).strftime("%d-%m-%Y")

        print(f"📊 Fetching NSE history via nselib ({from_date} to {to_date})...")

        for item in TARGET_SYMBOLS:
            ticker = item["ticker"]
            symbol_id = symbol_map[ticker]

            print(f" Downloading {ticker} via NSE...")
            try:
                df = capital_market.price_volume_and_deliverable_position_data(
                    symbol=ticker,
                    from_date=from_date,
                    to_date=to_date
                )

                if df is None or df.empty:
                    print(f"⚠️ No data returned for {ticker}")
                    continue

                df.columns = [c.strip() for c in df.columns]

                records_added = 0
                date_col_attr = getattr(MarketDataEOD, date_attr)

                for _, row in df.iterrows():
                    date_str = str(row['Date']).strip()
                    try:
                        trade_date = datetime.strptime(date_str, "%d-%b-%Y").date()
                    except ValueError:
                        trade_date = datetime.strptime(date_str, "%d-%m-%Y").date()

                    # Duplicate check using detected date column
                    stmt = select(MarketDataEOD).where(
                        MarketDataEOD.symbol_id == symbol_id,
                        date_col_attr == trade_date
                    )
                    res = await session.execute(stmt)
                    if res.scalar_one_or_none():
                        continue

                    # Numeric cleaning
                    open_p = float(str(row['OpenPrice']).replace(',', '').strip())
                    high_p = float(str(row['HighPrice']).replace(',', '').strip())
                    low_p = float(str(row['LowPrice']).replace(',', '').strip())
                    close_p = float(str(row['ClosePrice']).replace(',', '').strip())
                    vol = int(float(str(row['TotalTradedQuantity']).replace(',', '').strip()))

                    eod_kwargs = {
                        "symbol_id": symbol_id,
                        date_attr: trade_date,
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": close_p,
                        "volume": vol
                    }

                    eod_record = MarketDataEOD(**eod_kwargs)
                    session.add(eod_record)
                    records_added += 1

                await session.commit()
                print(f" Saved {records_added} official NSE EOD records for {ticker}.")

            except Exception as e:
                print(f"❌ Error fetching {ticker}: {str(e)}")

        print("🚀 Data seeding complete via official NSE data!")

if __name__ == "__main__":
    asyncio.run(seed_symbols_and_history())