# app/db/db_adapter.py
from typing import Dict, List, Optional

import pandas as pd
from app.db.session import AsyncSessionLocal
from sqlalchemy import text


async def fetch_universe_from_db(
    exchange_code: str = "NSE",
    days_back: int = 500,
    index_name: Optional[str] = None,
    symbols: Optional[List[str]] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Fetches daily OHLCV candles from PostgreSQL for screener/backtest execution.

    Selection Modes:
    1. `symbols` provided: Filters strictly for those explicit symbols.
    2. `index_name` provided: Filters for constituents of that index (e.g., 'RUSSELL 2000', 'NIFTY 500', 'S&P 500').
    3. Neither provided: Returns all active symbols for the given `exchange_code`.
    """
    print(
        f"📊 Fetching market data from DB for {exchange_code} (last {days_back} days) index_name {index_name}..."
    )

    params = {"exchange_code": exchange_code, "days_back": days_back}

    # Selection Logic: Index Filter vs. Whole Exchange Filter
    if index_name and not symbols:
        base_sql = """
            SELECT 
                s.trading_symbol AS symbol,
                m.date AS "Date",
                m.open AS "Open",
                m.high AS "High",
                m.low AS "Low",
                m.close AS "Close",
                m.volume AS "Volume"
            FROM market_data_all m
            JOIN symbols s ON s.id = m.symbol_id
            JOIN exchanges e ON e.id = s.exchange_id
            JOIN index_constituents ic ON ic.stock_symbol_id = s.id
            JOIN symbols idx ON idx.id = ic.index_symbol_id
            WHERE e.code = :exchange_code
              AND s.is_active = TRUE
              AND (UPPER(idx.trading_symbol) = :index_name OR UPPER(idx.name) = :index_name)
              AND m.date >= CURRENT_DATE - INTERVAL '1 day' * :days_back
        """
        params["index_name"] = index_name.strip().upper()
    else:
        base_sql = """
            SELECT 
                s.trading_symbol AS symbol,
                m.date AS "Date",
                m.open AS "Open",
                m.high AS "High",
                m.low AS "Low",
                m.close AS "Close",
                m.volume AS "Volume"
            FROM market_data_all m
            JOIN symbols s ON s.id = m.symbol_id
            JOIN exchanges e ON e.id = s.exchange_id
            WHERE e.code = :exchange_code
              AND s.is_active = TRUE
              AND m.date >= CURRENT_DATE - INTERVAL '1 day' * :days_back
        """

    # Dynamic symbol list override
    if symbols:
        clean_symbols = [str(sym).strip().upper() for sym in symbols if sym]
        if clean_symbols:
            base_sql += " AND UPPER(s.trading_symbol) = ANY(:symbols)"
            params["symbols"] = clean_symbols

    base_sql += " ORDER BY s.trading_symbol, m.date ASC;"

    async with AsyncSessionLocal() as session:
        result = await session.execute(text(base_sql), params)
        rows = result.mappings().all()

    if not rows:
        print("⚠️ No candles returned from database for given selection.")
        return {}

    # Convert query result to Pandas DataFrame
    df_all = pd.DataFrame(rows)
    df_all["Date"] = pd.to_datetime(df_all["Date"])

    # Group into dictionary of symbol -> OHLCV DataFrame
    universe: Dict[str, pd.DataFrame] = {}
    for symbol, df_group in df_all.groupby("symbol"):
        df_clean = df_group[["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
        df_clean = df_clean.sort_values("Date").reset_index(drop=True)
        universe[str(symbol).strip().upper()] = df_clean

    print(f"✅ Loaded {len(universe)} symbols from PostgreSQL.")
    return universe


async def fetch_index_data_from_db(
    index_symbol: str = "NIFTY 500", days_back: int = 500
) -> Optional[pd.DataFrame]:
    """
    Fetches daily candles for a benchmark index (e.g. 'NIFTY 500', 'S&P 500', '^NSEI', '^GSPC').
    Used for market health checks and Relative Strength (RS) calculations.
    """
    sql = """
        SELECT 
            m.date AS "Date",
            m.open AS "Open",
            m.high AS "High",
            m.low AS "Low",
            m.close AS "Close",
            m.volume AS "Volume"
        FROM market_data_all m
        JOIN symbols s ON s.id = m.symbol_id
        WHERE (UPPER(s.trading_symbol) = :index_symbol OR UPPER(s.name) = :index_symbol OR s.yf_symbol = :index_symbol)
          AND m.date >= CURRENT_DATE - INTERVAL '1 day' * :days_back
        ORDER BY m.date ASC;
    """
    params = {"index_symbol": index_symbol.strip().upper(), "days_back": days_back}

    async with AsyncSessionLocal() as session:
        result = await session.execute(text(sql), params)
        rows = result.mappings().all()

    if not rows:
        print(f"⚠️ Benchmark index '{index_symbol}' not found in database.")
        return None

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)
