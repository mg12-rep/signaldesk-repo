import asyncio

import pandas as pd
from app.db.session import AsyncSessionLocal
from app.services.indicators import compute_all_indicators
from sqlalchemy import text


async def test_engine():
    async with AsyncSessionLocal() as session:
        # Fetch 300 days of data for RELIANCE or AAPL
        query = text("""
            SELECT m.date, m.open, m.high, m.low, m.close, m.volume, s.trading_symbol
            FROM market_data_all m
            JOIN symbols s ON s.id = m.symbol_id
            WHERE s.trading_symbol IN ('RELIANCE', 'AAPL')
            ORDER BY m.date ASC;
        """)
        res = await session.execute(query)
        rows = res.mappings().all()

        if not rows:
            print("❌ No candles found in `market_data_all`. Run ingestion script first.")
            return

        df = pd.DataFrame(rows)
        symbol = df["trading_symbol"].iloc[0]
        print(f"📊 Calculating indicators for {symbol} ({len(df)} candles)...")

        df_calc = compute_all_indicators(df)

        print(f"\n✅ Indicators computed successfully! Latest values for {symbol}:")
        latest = df_calc.iloc[-1]
        print(f"  📅 Date: {latest['date']}")
        print(f"  💵 Close: {latest['close']}")
        print(f"  📈 SMA 20/50/200: {latest['sma_20']:.2f} | {latest['sma_50']:.2f} | {latest['sma_200']:.2f}")
        print(f"  📉 RSI (14): {latest['rsi_14']:.2f}")
        print(f"  📊 MACD / Signal: {latest['macd']:.2f} / {latest['macd_signal']:.2f}")
        print(f"  ⚡ Supertrend Dir: {'Bullish' if latest['supertrend_dir'] == 1 else 'Bearish'}")
        print(f"  🔊 Vol Spike: {latest['vol_spike']}")


if __name__ == "__main__":
    asyncio.run(test_engine())