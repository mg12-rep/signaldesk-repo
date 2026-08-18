import asyncio

from app.services.screener import run_market_screener


async def test_screener():
    print("🔍 Running Momentum Screener Test...")
    print("   Criteria: Close > SMA 200 AND RSI > 50\n")

    conditions = [
        {"field": "close", "op": ">", "value": "sma_200"},
        {"field": "rsi_14", "op": ">", "value": 50},
    ]

    results = await run_market_screener(conditions=conditions, limit=10)

    print(f"✅ Screener match count: {len(results)}\n")
    for stock in results:
        print(f"  📌 {stock['symbol']} ({stock['exchange']}): Close=${stock['close']} | RSI={stock['rsi_14']:.2f} | Supertrend={stock['supertrend_dir']}")


if __name__ == "__main__":
    asyncio.run(test_screener())