import os
import re
from pathlib import Path

from dotenv import load_dotenv
from upstox_totp import UpstoxTOTP

load_dotenv()

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def refresh_upstox_token() -> str:
    """Automates headless TOTP login and persists the access token to .env."""
    try:
        upx = UpstoxTOTP()
        response = upx.app_token.get_access_token()

        if response.success and response.data:
            new_token = response.data.access_token
            print(
                f"✅ Token generated successfully for user: {response.data.user_name}"
            )

            # Update .env file in place
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
        return ""


if __name__ == "__main__":
    refresh_upstox_token()
