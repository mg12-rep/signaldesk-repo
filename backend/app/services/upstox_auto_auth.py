import os
import re
import traceback
from pathlib import Path

from dotenv import load_dotenv
from upstox_totp import UpstoxTOTP


# Search upward until .env is found
def find_env_path() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        potential_env = parent / ".env"
        if potential_env.exists():
            return potential_env
    return Path(".env").resolve()


ENV_PATH = find_env_path()
load_dotenv(ENV_PATH, override=True)


def refresh_upstox_token() -> str:
    """Automates headless TOTP login and persists the access token to .env."""
    mobile = os.getenv("UPSTOX_USERNAME") or os.getenv("UPSTOX_MOBILE")
    pin = os.getenv("UPSTOX_PIN_CODE") or os.getenv("UPSTOX_PIN")
    totp_secret = os.getenv("UPSTOX_TOTP_SECRET") or os.getenv("UPSTOX_TOTP_KEY")
    client_id = os.getenv("UPSTOX_API_KEY") or os.getenv("UPSTOX_CLIENT_ID")
    client_secret = os.getenv("UPSTOX_API_SECRET") or os.getenv("UPSTOX_CLIENT_SECRET")
    print("***********************************")
    print(mobile)
    print("***********************************")
    redirect_uri = os.getenv(
        "UPSTOX_REDIRECT_URI", "http://127.0.0.1:8000/api/v1/auth/upstox/callback"
    )

    if not all([mobile, pin, totp_secret, client_id, client_secret]):
        print("❌ Missing Upstox credentials in .env")
        return ""
    try:
        upx = UpstoxTOTP()
        response = upx.app_token.get_access_token()

        if hasattr(response, "success") and response.success and response.data:
            new_token = response.data.access_token
            print(
                f"✅ Token generated successfully for user: {getattr(response.data, 'user_name', '')}"
            )

            if ENV_PATH.exists():
                content = ENV_PATH.read_text()
                if "UPSTOX_ACCESS_TOKEN=" in content:
                    content = re.sub(
                        r"UPSTOX_ACCESS_TOKEN=.*",
                        f"UPSTOX_ACCESS_TOKEN={new_token}",
                        content,
                    )
                else:
                    content += f"\nUPSTOX_ACCESS_TOKEN={new_token}\n"
                ENV_PATH.write_text(content)
                os.environ["UPSTOX_ACCESS_TOKEN"] = new_token
                print(f"📝 Saved UPSTOX_ACCESS_TOKEN to {ENV_PATH}")
            return new_token
        else:
            raise RuntimeError(f"Authentication failed: {response}")
    except Exception as e:
        print(f"❌ Error during auto token refresh: {e}")
        traceback.print_exc()
        return ""


if __name__ == "__main__":
    refresh_upstox_token()
