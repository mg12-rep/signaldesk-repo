from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Dynamically locate the backend directory root where .env lives
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    # Core Database Config (Provide default for fallback if needed)
    DATABASE_URL: str = (
        "postgresql+psycopg3://ddd:signaldesk123@localhost:5432/signaldesk"
    )

    # Zerodha Credentials
    KITE_API_KEY: str = ""
    KITE_API_SECRET: str = ""
    KITE_ACCESS_TOKEN: str = ""

    # Pre-trade Risk Controls
    RISK_MAX_ORDER_VALUE: float = 50000.0

    # Pydantic Settings Configuration (v2)
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH, env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
