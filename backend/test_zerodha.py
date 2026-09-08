import os

from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()

api_key = os.getenv("KITE_API_KEY")
access_token = os.getenv("KITE_ACCESS_TOKEN")


def test_connection():
    try:
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)

        print(api_key)
        print(access_token)

        # 1. Fetch Profile
        profile = kite.profile()
        print(f"Connected as: {profile.get('user_name')} ({profile.get('user_id')})")

        # 2. Fetch Equity Margins / Cash
        margins = kite.margins(segment="equity")
        available_cash = margins.get("available", {}).get(
            "live_balance", 0.0
        ) or margins.get("net", 0.0)
        print(f"Available Cash (INR): {available_cash}")

        # 3. Fetch Holdings Count
        holdings = kite.holdings()
        print(f"Total CNC Holdings: {len(holdings)}")

        # 4. Fetch Trades Count
        trades = kite.trades()
        print(f"Today's Executed Trades: {len(trades)}")

        print("\nAll Zerodha read tests passed successfully.")

    except Exception as e:
        print(f"Connection failed: {e}")


if __name__ == "__main__":
    test_connection()
