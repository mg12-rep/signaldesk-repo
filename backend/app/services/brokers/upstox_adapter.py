import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from app.services.brokers.base_adapter import BaseBrokerAdapter
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("upstox_adapter")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class UpstoxAdapter(BaseBrokerAdapter):
    def __init__(self, max_retries: int = 5, base_backoff_sec: float = 2.0):
        self.access_token = os.getenv("UPSTOX_ACCESS_TOKEN")
        self.api_key = os.getenv("UPSTOX_API_KEY")
        self.base_url = "https://api.upstox.com/v2"
        self.max_retries = max_retries
        self.base_backoff_sec = base_backoff_sec

    def _execute_request_with_retry(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
        json: Optional[Dict] = None,
    ) -> Optional[requests.Response]:
        """
        Executes HTTP requests with exponential backoff for:
        - Network disconnects / connection resets
        - HTTP 429 Rate Limit
        - HTTP 500/502/503/504 Transient Server Errors
        """
        attempt = 0
        while attempt < self.max_retries:
            try:
                if method.upper() == "GET":
                    response = requests.get(
                        url, headers=headers, params=params, timeout=15
                    )
                else:
                    response = requests.post(
                        url, headers=headers, json=json, timeout=15
                    )

                # Case 1: Success
                if response.status_code == 200:
                    return response

                # Case 2: Rate limit (HTTP 429)
                if response.status_code == 429:
                    wait_time = self.base_backoff_sec * (2**attempt)
                    logger.warning(
                        f"Upstox rate limited (429). Retrying in {wait_time:.1f}s (Attempt {attempt + 1}/{self.max_retries})..."
                    )
                    time.sleep(wait_time)
                    attempt += 1
                    continue

                # Case 3: Transient Upstox Server Errors (5xx)
                if response.status_code in [500, 502, 503, 504]:
                    wait_time = self.base_backoff_sec * (2**attempt)
                    logger.warning(
                        f"Upstox server error ({response.status_code}). Retrying in {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)
                    attempt += 1
                    continue

                # Case 4: Auth / Bad Request Errors (401 / 400) - No retry
                logger.error(
                    f"Upstox request failed with status {response.status_code}: {response.text}"
                )
                return response

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as e:
                attempt += 1
                wait_time = self.base_backoff_sec * (2**attempt)
                logger.warning(
                    f"Network drop / connection error: {e}. Reconnecting in {wait_time:.1f}s (Attempt {attempt}/{self.max_retries})..."
                )
                time.sleep(wait_time)

        logger.error(f"Max retries ({self.max_retries}) exceeded for URL: {url}")
        return None

    def fetch_historical_daily(
        self, instrument_key: str, days: int = 365
    ) -> pd.DataFrame:
        """
        Fetches daily OHLCV bars with automated reconnection and retry.
        """
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        url = f"{self.base_url}/historical-candle/{instrument_key}/day/{to_date}/{from_date}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}" if self.access_token else "",
        }

        response = self._execute_request_with_retry(
            method="GET", url=url, headers=headers
        )

        if not response or response.status_code != 200:
            logger.error(f"Failed to fetch historical bars for {instrument_key}")
            return pd.DataFrame()

        data = response.json()
        candles = data.get("data", {}).get("candles", [])
        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume", "oi"],
        )
        df["trade_date"] = pd.to_datetime(df["timestamp"]).dt.date
        df.drop(columns=["timestamp", "oi"], inplace=True)
        return df

    def place_order(
        self, symbol: str, exchange: str, qty: int, order_type: str, price: float = None
    ) -> Dict[str, Any]:
        """Dispatches orders with auto-retry on network disconnects."""
        url = f"{self.base_url}/order/place"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
        payload = {
            "quantity": qty,
            "product": "D",
            "validity": "DAY",
            "price": price if order_type.upper() == "LIMIT" else 0,
            "tag": "signaldesk",
            "instrument_token": symbol,
            "order_type": "LIMIT" if order_type.upper() == "LIMIT" else "MARKET",
            "transaction_type": "BUY",
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
        }
        response = self._execute_request_with_retry(
            method="POST", url=url, headers=headers, json=payload
        )
        return (
            response.json()
            if response
            else {"status": "error", "message": "Failed after max retries"}
        )

    def get_positions(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/portfolio/long-term-holdings"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
        response = self._execute_request_with_retry(
            method="GET", url=url, headers=headers
        )
        if response and response.status_code == 200:
            return response.json().get("data", [])
        return []


# Singleton instance
upstox_adapter = UpstoxAdapter()
