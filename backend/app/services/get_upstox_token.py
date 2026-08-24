import urllib.parse
import webbrowser

import requests

API_KEY = "139c8d4f-2367-40b1-9afe-33796f0e0b10"
API_SECRET = "xbq6367pb1"
REDIRECT_URI = "https://127.0.0.1:5000"

# Step A: Open Browser for 1-Click Login
auth_url = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={API_KEY}&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
print("Opening browser to authorize Upstox...")
webbrowser.open(auth_url)

# Step B: Paste the 'code' query parameter from the redirected browser URL
auth_code = input("\nEnter the 'code=' value from the redirected URL: ").strip()

# Step C: Exchange Code for Access Token
token_url = "https://api.upstox.com/v2/login/authorization/token"
payload = {
    "code": auth_code,
    "client_id": API_KEY,
    "client_secret": API_SECRET,
    "redirect_uri": REDIRECT_URI,
    "grant_type": "authorization_code",
}
headers = {
    "accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
}

resp = requests.post(token_url, data=payload, headers=headers)
token_data = resp.json()

if "access_token" in token_data:
    print("\n✅ SUCCESS! Copy this to your backend/.env as UPSTOX_ACCESS_TOKEN:")
    print(f"\nUPSTOX_ACCESS_TOKEN={token_data['access_token']}\n")
else:
    print("\n❌ Error generating token:", token_data)
