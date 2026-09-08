import json
import os

from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv(override=True)

api_key = os.getenv("KITE_API_KEY", "").strip()
access_token = os.getenv("KITE_ACCESS_TOKEN", "").strip()

print(
    f"Testing with API Key: {api_key[:4]}... and Access Token: {access_token[:6]}...\n"
)

kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

tests = [
    ("Profile", lambda: kite.profile()),
    ("Holdings (CNC)", lambda: kite.holdings()),
    ("Positions (Day/Net)", lambda: kite.positions()),
    ("Trades (Executed Today)", lambda: kite.trades()),
    ("Margins (All)", lambda: kite.margins()),
    ("Margins (Equity segment)", lambda: kite.margins(segment="equity")),
]

for name, fn in tests:
    try:
        res = fn()
        count = len(res) if isinstance(res, (list, dict)) else 1
        print(f"✅ {name}: SUCCESS (returned {count} records/keys)")
        if "Margins" in name:
            print(f"   Payload: {json.dumps(res, indent=2)[:300]}...\n")
    except Exception as e:
        print(f"❌ {name}: FAILED -> {e}")
