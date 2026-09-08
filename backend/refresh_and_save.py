import os
import re

from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv(override=True)

api_key = os.getenv("KITE_API_KEY", "").strip()
api_secret = os.getenv("KITE_API_SECRET", "").strip()

print(f"API Key: {api_key}")
print(
    f"\n1. Open this URL in browser:\nhttps://kite.zerodha.com/connect/login?v=3&api_key={api_key}\n"
)

req_token = input("2. Enter the new request_token from URL bar: ").strip()

try:
    kite = KiteConnect(api_key=api_key)
    session_data = kite.generate_session(req_token, api_secret=api_secret)
    access_token = session_data["access_token"]
    print(f"\n✅ New Access Token: {access_token}")

    # Auto-update .env file
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        env_path = ".env"

    with open(env_path, "r") as f:
        content = f.read()

    if "KITE_ACCESS_TOKEN=" in content:
        content = re.sub(
            r"KITE_ACCESS_TOKEN=.*", f"KITE_ACCESS_TOKEN={access_token}", content
        )
    else:
        content += f"\nKITE_ACCESS_TOKEN={access_token}\n"

    with open(env_path, "w") as f:
        f.write(content)

    print(f"✅ Saved directly to {env_path}!")

    # Verify immediately
    kite.set_access_token(access_token)
    profile = kite.profile()
    margins = kite.margins(segment="equity")
    cash = margins.get("available", {}).get("live_balance", 0.0) or margins.get(
        "net", 0.0
    )
    print(f"✅ Connected as: {profile.get('user_name')}")
    print(f"✅ Live Cash (INR): {cash}")

except Exception as e:
    print(f"❌ Error: {e}")
