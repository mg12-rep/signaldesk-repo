import os

from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()

api_key = os.getenv("KITE_API_KEY", "").strip()
api_secret = os.getenv("KITE_API_SECRET", "").strip()

print(f"API Key loaded: {api_key[:4]}...{api_key[-4:] if len(api_key) > 4 else ''}")

# 1. Open this link in browser:
login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
print(f"\n1. Open this URL in browser:\n{login_url}\n")

# 2. Paste the fresh request_token from URL bar
req_token = input("2. Enter the new request_token from the redirected URL: ").strip()

try:
    kite = KiteConnect(api_key=api_key)
    session_data = kite.generate_session(req_token, api_secret=api_secret)
    access_token = session_data["access_token"]
    print(f"\n Generated Access Token: {access_token}")

    # 3. Direct Test
    kite.set_access_token(access_token)
    profile = kite.profile()
    print(
        f" Connected successfully as: {profile.get('user_name')} ({profile.get('user_id')})"
    )

except Exception as e:
    print(f"\n Error: {e}")
