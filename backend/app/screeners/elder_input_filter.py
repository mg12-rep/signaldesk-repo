import logging
import os
from pathlib import Path
from typing import List

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
logger = logging.getLogger("elder_input_filter")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url, pool_size=5, max_overflow=5)


def generate_elder_universe_csv(
    market: str = "NSE",
    output_dir: str = "C:/work/signaldesk/data",
    min_price: float = 100.0,
    max_price: float = 10000.0,
) -> Path:
    """
    Screens the active universe (NSE 500 or S&P 500) for daily trend alignment:
    - 100 < Close < 10,000
    - Close > SMA 50
    - Close > SMA 150
    - Close > SMA 200
    - Close > EMA 21
    - Close > EMA 8

    Exports matching tickers to elder_input_{nse|us}_stocks.csv with column 'Symbol'.
    """
    market = market.upper().strip()
    if market == "NSE":
        symbols_query = text("""
            SELECT DISTINCT s.id, s.trading_symbol
            FROM symbols s
            JOIN index_constituents ic ON s.id = ic.stock_symbol_id
            WHERE ic.index_symbol_id = 2
              AND s.is_active = TRUE
            ORDER BY s.trading_symbol;
        """)
        filename = "elder_input_nse_stocks.csv"
    else:  # US / S&P 500
        symbols_query = text("""
            SELECT DISTINCT s.id, s.trading_symbol
            FROM symbols s
            JOIN index_constituents ic ON s.id = ic.stock_symbol_id
            WHERE ic.index_symbol_id IN (559, 2978)
              AND s.is_active = TRUE
            ORDER BY s.trading_symbol;
        """)
        filename = "elder_input_us_stocks.csv"

    out_path = Path(output_dir) / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with engine.connect() as conn:
        symbols = conn.execute(symbols_query).fetchall()

    logger.info(
        f"Screening {len(symbols)} {market} universe constituents on Daily timeframe..."
    )

    bars_query = text("""
        SELECT date AS "Date", close AS "Close"
        FROM market_data_all
        WHERE symbol_id = :sid
        ORDER BY date ASC;
    """)

    qualified_symbols: List[str] = []

    for idx, (sid, sym) in enumerate(symbols, start=1):
        with engine.connect() as conn:
            df = pd.read_sql(bars_query, conn, params={"sid": sid})

        # Need at least 200 bars to compute 200 SMA
        if len(df) < 200:
            continue

        # Indicator calculations on Daily timeframe
        df["SMA50"] = df["Close"].rolling(50).mean()
        df["SMA150"] = df["Close"].rolling(150).mean()
        df["SMA200"] = df["Close"].rolling(200).mean()
        df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()
        df["EMA8"] = df["Close"].ewm(span=8, adjust=False).mean()

        last_bar = df.iloc[-1]
        close = float(last_bar["Close"])

        # Filter Conditions
        price_in_range = min_price < close < max_price
        above_smas = (
            close > last_bar["SMA50"]
            and last_bar["SMA50"] > last_bar["SMA150"]
            and last_bar["SMA150"] > last_bar["SMA200"]
        )
        above_emas = close > last_bar["EMA8"] and last_bar["EMA8"] > last_bar["EMA21"]
        emas_above_smas = last_bar["EMA21"] > last_bar["SMA50"]

        if price_in_range and above_smas and above_emas and emas_above_smas:
            qualified_symbols.append(sym)

    # Export to CSV with column name 'Symbol'
    df_out = pd.DataFrame({"Symbol": sorted(qualified_symbols)})
    df_out.to_csv(out_path, index=False)

    logger.info(f"✅ Generated {out_path} with {len(df_out)} qualified symbols.")
    return out_path


if __name__ == "__main__":
    generate_elder_universe_csv(market="NSE")
    generate_elder_universe_csv(market="US")
