import asyncio
import io

import pandas as pd
import requests
from app.db.models import AssetClass, Exchange, IndexConstituent, Symbol
from app.db.session import AsyncSessionLocal
from sqlalchemy import select

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Reliable sources for US indices
SP500_WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_WIKI = "https://en.wikipedia.org/wiki/Nasdaq-100"
RUSSELL2000_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"  # Fallback source


async def seed_us_symbols():
    async with AsyncSessionLocal() as session:
        print("🚀 Starting US Symbol Seeding Process (S&P 500, NASDAQ 100, Russell 2000)...")

        # 1. Ensure US Exchanges exist
        async def get_or_create_exchange(code: str, name: str):
            stmt = select(Exchange).where(Exchange.code == code)
            res = await session.execute(stmt)
            ex = res.scalar_one_or_none()
            if not ex:
                ex = Exchange(code=code, name=name, country="US", timezone="America/New_York")
                session.add(ex)
                await session.commit()
                await session.refresh(ex)
            return ex

        nasdaq_ex = await get_or_create_exchange("NASDAQ", "NASDAQ Stock Market")
        nyse_ex = await get_or_create_exchange("NYSE", "New York Stock Exchange")

        # Helper to get index object
        async def get_index_symbol(trading_symbol: str):
            stmt = select(Symbol).where(Symbol.trading_symbol == trading_symbol, Symbol.is_index == True)
            res = await session.execute(stmt)
            return res.scalars().first()

        sp500_idx = await get_index_symbol("S&P 500")
        nasdaq100_idx = await get_index_symbol("NASDAQ 100")
        russell_idx = await get_index_symbol("RUSSELL 2000")

        # Helper to insert or fetch stock
        async def get_or_create_stock(symbol_str: str, company_name: str, default_ex: Exchange):
            clean_sym = str(symbol_str).replace(".", "-").strip().upper()
            if not clean_sym or clean_sym in ["NAN", "SYMBOL", "TICKER"]:
                return None

            stmt = select(Symbol).where(Symbol.trading_symbol == clean_sym)
            res = await session.execute(stmt)
            stock = res.scalars().first()

            if not stock:
                stock = Symbol(
                    trading_symbol=clean_sym,
                    yf_symbol=clean_sym,
                    name=company_name or clean_sym,
                    exchange_id=default_ex.id,
                    asset_class=AssetClass.EQUITY,
                    is_index=False,
                    is_active=True,
                )
                session.add(stock)
                await session.flush()
            return stock

        # Helper to link stock to index
        async def link_to_index(stock_obj, index_obj):
            if not stock_obj or not index_obj:
                return
            stmt = select(IndexConstituent).where(
                IndexConstituent.index_symbol_id == index_obj.id,
                IndexConstituent.stock_symbol_id == stock_obj.id,
            )
            res = await session.execute(stmt)
            if not res.scalars().first():
                session.add(IndexConstituent(index_symbol_id=index_obj.id, stock_symbol_id=stock_obj.id))

        # -----------------------------------------------------------
        # A. NASDAQ 100 (Wikipedia)
        # -----------------------------------------------------------
        print("\n📥 Fetching NASDAQ 100 from Wikipedia...")
        try:
            resp = requests.get(NASDAQ100_WIKI, headers=HEADERS, timeout=15)
            tables = pd.read_html(io.StringIO(resp.text))
            
            # Find table containing ticker symbols
            df_ndx = None
            for t in tables:
                cols_str = " ".join([str(c).lower() for c in t.columns])
                if "ticker" in cols_str or "symbol" in cols_str:
                    df_ndx = t
                    break

            if df_ndx is not None:
                sym_col = [c for c in df_ndx.columns if "ticker" in str(c).lower() or "symbol" in str(c).lower()][0]
                name_col = [c for c in df_ndx.columns if "company" in str(c).lower() or "name" in str(c).lower()]
                name_col_name = name_col[0] if name_col else None

                ndx_count = 0
                for _, row in df_ndx.iterrows():
                    sym = str(row[sym_col])
                    name = str(row[name_col_name]) if name_col_name else sym
                    stk = await get_or_create_stock(sym, name, nasdaq_ex)
                    if stk:
                        await link_to_index(stk, nasdaq100_idx)
                        ndx_count += 1
                await session.commit()
                print(f"✅ Processed {ndx_count} NASDAQ 100 stocks.")
        except Exception as e:
            print(f"❌ Error fetching NASDAQ 100: {e}")

        # -----------------------------------------------------------
        # B. RUSSELL 2000 (ikoniaris GitHub Repository)
        # -----------------------------------------------------------
        print("\n📥 Fetching Russell 2000 constituents...")
        r2000_url = "https://raw.githubusercontent.com/ikoniaris/Russell2000/master/russell_2000_components.csv"
        try:
            resp = requests.get(r2000_url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                df_r = pd.read_csv(io.StringIO(resp.text))
                
                # Column headers in this file are 'Ticker' and 'Name'
                sym_col = [c for c in df_r.columns if "ticker" in str(c).lower() or "symbol" in str(c).lower()][0]
                name_col = [c for c in df_r.columns if "company" in str(c).lower() or "name" in str(c).lower()]
                name_col_name = name_col[0] if name_col else None

                r_count = 0
                for _, row in df_r.iterrows():
                    sym = str(row[sym_col]).strip()
                    name = str(row[name_col_name]).strip() if name_col_name else sym
                    
                    stk = await get_or_create_stock(sym, name, nasdaq_ex)
                    if stk:
                        await link_to_index(stk, russell_idx)
                        r_count += 1
                        
                await session.commit()
                print(f"✅ Processed {r_count} Russell 2000 stocks.")
            else:
                print(f"⚠️ Russell 2000 URL returned status {resp.status_code}")
        except Exception as e:
            print(f"❌ Error fetching Russell 2000: {e}")

        print("\n🎉 US Symbol Seeding Complete!")


if __name__ == "__main__":
    asyncio.run(seed_us_symbols())