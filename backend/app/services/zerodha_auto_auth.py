import logging
import os
import re
from urllib.parse import parse_qs, urlparse

import pyotp
import requests
from dotenv import load_dotenv
from kiteconnect import KiteConnect

logger = logging.getLogger("zerodha_auth")


def auto_login_zerodha() -> str:
    """Performs headless automated login for Kite Connect using TOTP
    and updates the KITE_ACCESS_TOKEN in .env.
    """
    load_dotenv(override=True)

    user_id = os.getenv("KITE_USER_ID", "").strip()
    password = os.getenv("KITE_PASSWORD", "").strip()
    totp_key = os.getenv("KITE_TOTP_KEY", "").strip()
    api_key = os.getenv("KITE_API_KEY", "").strip()
    api_secret = os.getenv("KITE_API_SECRET", "").strip()

    if not all([user_id, password, totp_key, api_key, api_secret]):
        raise ValueError("Missing Zerodha credentials in .env file.")

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }

    # Step 1: Submit Login
    login_url = "https://kite.zerodha.com/api/login"
    login_res = session.post(
        login_url,
        data={"user_id": user_id, "password": password},
        headers=headers,
        timeout=10,
    )
    login_data = login_res.json()
    if login_data.get("status") != "success":
        raise RuntimeError(f"Login failed: {login_data.get('message')}")

    request_id = login_data["data"]["request_id"]

    # Step 2: Generate TOTP & Submit 2FA
    totp = pyotp.TOTP(totp_key)
    twofa_pin = totp.now()

    twofa_url = "https://kite.zerodha.com/api/twofa"
    twofa_res = session.post(
        twofa_url,
        data={
            "user_id": user_id,
            "request_id": request_id,
            "twofa_value": twofa_pin,
            "twofa_type": "totp",
            "skip_session": "true",
        },
        headers=headers,
        timeout=10,
    )
    twofa_data = twofa_res.json()
    if twofa_data.get("status") != "success":
        raise RuntimeError(f"2FA failed: {twofa_data.get('message')}")

    # Step 3: Trigger OAuth Connect redirect without following local redirect
    # Step 3: Trigger OAuth Connect redirect and follow internal Zerodha redirects
    connect_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"

    current_url = connect_url
    request_token = None

    # Follow up to 5 redirects, but stop before contacting localhost/127.0.0.1
    for _ in range(5):
        res = session.get(
            current_url, headers=headers, timeout=10, allow_redirects=False
        )
        location = res.headers.get("Location") or res.headers.get("location")

        if not location:
            break

        parsed_url = urlparse(location)
        params = parse_qs(parsed_url.query)

        # Check if request_token is in this redirect URL
        if "request_token" in params:
            request_token = params["request_token"][0]
            break

        # If it's a relative URL, reconstruct the full URL
        if not location.startswith("http"):
            current_url = f"https://kite.zerodha.com{location}"
        else:
            current_url = location

    if not request_token:
        raise RuntimeError(
            f"Failed to capture request_token. Last redirect target was: {current_url}"
        )

    # Step 4: Generate Kite Access Token directly in-memory
    kite = KiteConnect(api_key=api_key)
    session_data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session_data["access_token"]

    # Step 5: Update environment variables and .env file
    os.environ["KITE_ACCESS_TOKEN"] = access_token

    env_path = os.path.join(os.path.dirname(__file__), "../../../.env")
    if not os.path.exists(env_path):
        env_path = ".env"

    if os.path.exists(env_path):
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

    logger.info("Successfully generated and saved new Zerodha access token.")
    return access_token
