import asyncio
import io
import re

import pandas as pd
import requests
from app.db.models import AssetClass, Exchange, IndexConstituent, Symbol
from app.db.session import AsyncSessionLocal
from sqlalchemy import select

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 1. Official Master List for ALL Listed Equities on NSE (~2,400+ stocks)
NSE_ALL_EQUITIES_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

# 2. Index Constituent Lists (for tagging index membership)
NIFTY_50_URL = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"
NIFTY_500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

# 3. ETF List
NSE_ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"


async def seed_nse_symbols():
    async with AsyncSessionLocal() as session:
        print("🚀 Starting Complete NSE Seeding Process...")

        # ----------------------------------------------------
        # 1. Ensure NSE Exchange Exists
        # ----------------------------------------------------
        stmt = select(Exchange).where(Exchange.code == "NSE")
        res = await session.execute(stmt)
        nse_exchange = res.scalar_one_or_none()

        if not nse_exchange:
            nse_exchange = Exchange(
                code="NSE",
                name="National Stock Exchange of India",
                country="IN",
                timezone="Asia/Kolkata",
            )
            session.add(nse_exchange)
            await session.commit()
            await session.refresh(nse_exchange)
            print("✅ Ensured NSE Exchange entry exists.")

        # Helper to get/create index symbols
        async def get_or_create_index(trading_sym: str, yf_sym: str, name: str):
            stmt = select(Symbol).where(
                Symbol.trading_symbol == trading_sym,
                Symbol.exchange_id == nse_exchange.id,
            )
            res = await session.execute(stmt)
            idx = res.scalar_one_or_none()
            if not idx:
                idx = Symbol(
                    trading_symbol=trading_sym,
                    yf_symbol=yf_sym,
                    name=name,
                    exchange_id=nse_exchange.id,
                    asset_class=AssetClass.INDEX,
                    is_index=True,
                    is_active=True,
                )
                session.add(idx)
                await session.commit()
                await session.refresh(idx)
            return idx

        nifty50_index = await get_or_create_index("NIFTY 50", "^NSEI", "Nifty 50 Index")
        nifty500_index = await get_or_create_index("NIFTY 500", "^CRSLDX", "Nifty 500 Index")
        print("✅ Ensured NIFTY 50 and NIFTY 500 Index entries exist.")

        # ----------------------------------------------------
        # 2. Seed ALL NSE Equities from EQUITY_L.csv
        # ----------------------------------------------------
        print("📥 Fetching Master List of ALL Equities (EQUITY_L.csv)...")
        try:
            resp = requests.get(NSE_ALL_EQUITIES_URL, headers=HEADERS, timeout=20)
            df_all = pd.read_csv(io.StringIO(resp.text))

            eq_count = 0
            for _, row in df_all.iterrows():
                # Filter for mainboard equities (EQ series) or Trade-for-Trade (BE series)
                series = str(row.get(" SERIES", row.get("SERIES", ""))).strip().upper()
                if series not in ["EQ", "BE", "BZ"]:
                    continue

                sym = str(row.get("SYMBOL", "")).strip()
                name = str(row.get("NAME OF COMPANY", row.get("NAME", sym))).strip()

                if not sym or sym.lower() == "nan":
                    continue

                stmt = select(Symbol).where(
                    Symbol.trading_symbol == sym,
                    Symbol.exchange_id == nse_exchange.id,
                )
                res = await session.execute(stmt)
                stock = res.scalar_one_or_none()

                if not stock:
                    stock = Symbol(
                        trading_symbol=sym,
                        yf_symbol=f"{sym}.NS",
                        name=name,
                        exchange_id=nse_exchange.id,
                        asset_class=AssetClass.EQUITY,
                        is_index=False,
                        is_active=True,
                    )
                    session.add(stock)
                    eq_count += 1

            await session.commit()
            print(f"✅ Successfully seeded {eq_count} new equity symbols from Master List.")
        except Exception as e:
            print(f"❌ Error fetching EQUITY_L.csv: {e}")

        # ----------------------------------------------------
        # 3. Link Index Constituents (Nifty 50 / Nifty 500)
        # ----------------------------------------------------
        async def link_index_csv(url: str, index_symbol_obj: Symbol):
            print(f"📥 Tagging constituents for {index_symbol_obj.trading_symbol}...")
            resp = requests.get(url, headers=HEADERS, timeout=15)
            df = pd.read_csv(io.StringIO(resp.text))

            count = 0
            for _, row in df.iterrows():
                sym = str(row["Symbol"]).strip()

                stmt = select(Symbol).where(
                    Symbol.trading_symbol == sym,
                    Symbol.exchange_id == nse_exchange.id,
                )
                res = await session.execute(stmt)
                stock = res.scalar_one_or_none()

                if stock:
                    stmt_c = select(IndexConstituent).where(
                        IndexConstituent.index_symbol_id == index_symbol_obj.id,
                        IndexConstituent.stock_symbol_id == stock.id,
                    )
                    res_c = await session.execute(stmt_c)
                    if not res_c.scalar_one_or_none():
                        session.add(
                            IndexConstituent(
                                index_symbol_id=index_symbol_obj.id,
                                stock_symbol_id=stock.id,
                            )
                        )
                        count += 1
            await session.commit()
            print(f"✅ Linked {count} constituents to {index_symbol_obj.trading_symbol}.")

        await link_index_csv(NIFTY_50_URL, nifty50_index)
        await link_index_csv(NIFTY_500_URL, nifty500_index)

        # ----------------------------------------------------
        # 4. Fetch and Seed ETFs using NSE_ETF_URL
        # ----------------------------------------------------
        print("📥 Fetching Master List of ETFs...")
        
        # Backup GitHub mirror URL in case NSE archives block/return HTML error
        ETF_SOURCES = [
            NSE_ETF_URL,
            "https://raw.githubusercontent.com/anandm/nse-india-data/master/etf.csv"
        ]

        etf_df = None
        for source_url in ETF_SOURCES:
            try:
                print(f"   Trying source: {source_url}")
                resp_etf = requests.get(source_url, headers=HEADERS, timeout=15)
                # Ensure response is HTTP 200 and CSV text (not HTML page)
                if resp_etf.status_code == 200 and not resp_etf.text.strip().startswith("<"):
                    etf_df = pd.read_csv(io.StringIO(resp_etf.text), on_bad_lines="skip", engine="python")
                    print(f"   ✅ Successfully retrieved ETF CSV from {source_url}")
                    break
            except Exception as e:
                print(f"   ⚠️ Could not fetch from {source_url}: {e}")

        if etf_df is not None:
            # Dynamically identify symbol and company/underlying name columns
            cols_lower = [str(c).lower() for c in etf_df.columns]
            sym_col_name = etf_df.columns[[i for i, c in enumerate(cols_lower) if "symbol" in c or "ticker" in c][0]]
            
            name_cols = [i for i, c in enumerate(cols_lower) if "company" in c or "name" in c or "underlying" in c or "assets" in c]
            name_col_name = etf_df.columns[name_cols[0]] if name_cols else sym_col_name

            etf_count = 0
            for _, row in etf_df.iterrows():
                sym = str(row[sym_col_name]).strip().upper()
                name = str(row[name_col_name]).strip() if name_col_name else sym

                # Skip blank or invalid rows
                if not sym or sym in ["NAN", "SYMBOL", "TICKER", "NONE"] or len(sym) > 20 or sym.startswith("<"):
                    continue

                stmt = select(Symbol).where(
                    Symbol.trading_symbol == sym,
                    Symbol.exchange_id == nse_exchange.id,
                )
                res = await session.execute(stmt)
                etf_symbol = res.scalar_one_or_none()

                if not etf_symbol:
                    etf_symbol = Symbol(
                        trading_symbol=sym,
                        yf_symbol=f"{sym}.NS",
                        name=name,
                        exchange_id=nse_exchange.id,
                        asset_class=AssetClass.ETF,
                        is_index=False,
                        is_active=True,
                    )
                    session.add(etf_symbol)
                    etf_count += 1
                else:
                    etf_symbol.asset_class = AssetClass.ETF

            await session.commit()
            print(f"✅ Successfully seeded/updated {etf_count} NSE ETFs.")
        else:
            print("❌ Failed to fetch ETF data from all sources.")
    

        print("🎉 Complete NSE Seeding Finished!")


if __name__ == "__main__":
    asyncio.run(seed_nse_symbols())