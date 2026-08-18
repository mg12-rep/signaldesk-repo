import asyncio
import io

import pandas as pd
import requests
from app.db.models import AssetClass, Exchange, Symbol
from app.db.session import AsyncSessionLocal
from sqlalchemy import select

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Reliable open source for active NSE ETFs list
NSE_ETF_MASTER_URL = "https://raw.githubusercontent.com/anandm/nse-india-data/master/etf.csv"

async def seed_nse_etfs_direct():
    async with AsyncSessionLocal() as session:
        print("📥 Fetching official NSE ETF list...")
        
        # 1. Fetch Exchange
        res = await session.execute(select(Exchange).where(Exchange.code == "NSE"))
        nse_exchange = res.scalar_one_or_none()
        if not nse_exchange:
            print("❌ NSE exchange not found in DB.")
            return

        try:
            resp = requests.get(NSE_ETF_MASTER_URL, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                df_etf = pd.read_csv(io.StringIO(resp.text))
                
                # Identify Symbol & Name columns
                sym_col = [c for c in df_etf.columns if "symbol" in str(c).lower() or "ticker" in str(c).lower()][0]
                name_col = [c for c in df_etf.columns if "company" in str(c).lower() or "name" in str(c).lower() or "underlying" in str(c).lower()]
                name_col_name = name_col[0] if name_col else sym_col

                inserted_count = 0
                updated_count = 0

                for _, row in df_etf.iterrows():
                    sym = str(row[sym_col]).strip().upper()
                    name = str(row[name_col_name]).strip() if name_col_name else sym

                    if not sym or sym in ["NAN", "SYMBOL", "TICKER"] or len(sym) > 20:
                        continue

                    # Check if symbol exists in DB
                    stmt = select(Symbol).where(
                        Symbol.trading_symbol == sym,
                        Symbol.exchange_id == nse_exchange.id
                    )
                    res = await session.execute(stmt)
                    stock = res.scalars().first()

                    if not stock:
                        stock = Symbol(
                            trading_symbol=sym,
                            yf_symbol=f"{sym}.NS",
                            name=name,
                            exchange_id=nse_exchange.id,
                            asset_class=AssetClass.ETF,
                            is_index=False,
                            is_active=True,
                        )
                        session.add(stock)
                        inserted_count += 1
                    else:
                        stock.asset_class = AssetClass.ETF
                        updated_count += 1

                await session.commit()
                print(f"✅ ETF Seeding Complete: {inserted_count} new ETFs inserted, {updated_count} existing symbols updated to AssetClass.ETF.")
            else:
                print(f"⚠️ Failed to fetch ETF list. Status: {resp.status_code}")
        except Exception as e:
            print(f"❌ Error seeding ETFs: {e}")

if __name__ == "__main__":
    asyncio.run(seed_nse_etfs_direct())