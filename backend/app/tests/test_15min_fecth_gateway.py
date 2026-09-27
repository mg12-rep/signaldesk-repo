from app.services.brokers.ibkr_adapter import ibkr_adapter


def test_15min_fetch():
    print("Fetching last 2 days of 15m bars for AAPL via IB Gateway...")
    df = ibkr_adapter.fetch_15min_historical_bars("AAPL", days=2)

    if df.empty:
        print("❌ No bars returned. Check IB Gateway connectivity or permissions.")
    else:
        print(f"✅ Successfully received {len(df)} bars!")
        print(df.tail(5))


if __name__ == "__main__":
    test_15min_fetch()
