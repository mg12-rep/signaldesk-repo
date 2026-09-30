import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from app.services.brokers.base_adapter import BaseBrokerAdapter
from dotenv import load_dotenv

# Import your existing auto-auth function (adjust import path to where source 18 resides)
try:
    from app.services.upstox_auto_auth import refresh_upstox_token
except ImportError:
    try:
        from app.services.upstox_auto_auth import refresh_upstox_token
    except ImportError:
        refresh_upstox_token = None

load_dotenv(override=True)
logger = logging.getLogger("upstox_adapter")


class UpstoxAdapter(BaseBrokerAdapter):
    def __init__(self, max_retries: int = 3, base_backoff_sec: float = 1.5):
        self.max_retries = max_retries
        self.base_backoff_sec = base_backoff_sec
        self.base_url = "https://api.upstox.com/v2"
        self._is_refreshing = False
        self._init_client()

    def _init_client(self):
        """Reloads credentials dynamically from environment."""
        load_dotenv(override=True)
        self.access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
        self.api_key = os.getenv("UPSTOX_API_KEY", "").strip()

    def _refresh_and_reconnect(self) -> bool:
        """Executes auto-login via TOTP and updates the local access token."""
        if self._is_refreshing:
            return False
        self._is_refreshing = True
        try:
            logger.info(
                "Upstox token expired/invalid (401). Refreshing token via auto-login..."
            )
            if refresh_upstox_token:
                new_token = refresh_upstox_token()
                if new_token:
                    self.access_token = new_token
                    os.environ["UPSTOX_ACCESS_TOKEN"] = new_token
                    logger.info(
                        "Successfully refreshed and updated UPSTOX_ACCESS_TOKEN."
                    )
                    return True
            logger.error(
                "refresh_upstox_token function could not be loaded or returned empty."
            )
            return False
        except Exception as e:
            logger.error(f"Failed auto-refreshing Upstox token: {e}")
            return False
        finally:
            self._is_refreshing = False

    def _execute_request_with_retry(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
    ) -> Optional[requests.Response]:
        """
        Executes HTTP requests with retry logic for:
        - HTTP 401: Auto-refresh token and retry request with updated Bearer header
        - HTTP 429: Rate limit backoff
        - HTTP 5xx / Connection timeouts
        """
        if not self.access_token:
            self._init_client()

        req_headers = headers.copy() if headers else {}
        if self.access_token:
            req_headers["Authorization"] = f"Bearer {self.access_token}"
        req_headers["Accept"] = "application/json"

        attempt = 0
        token_refreshed = False

        while attempt < self.max_retries:
            try:
                if method.upper() == "GET":
                    response = requests.get(
                        url, headers=req_headers, params=params, timeout=15
                    )
                else:
                    response = requests.post(
                        url, headers=req_headers, json=json_data, timeout=15
                    )

                # Case 1: Success
                if response.status_code == 200:
                    return response

                # Case 2: Auth failure (401) - Attempt auto-login once
                if response.status_code == 401 and not token_refreshed:
                    logger.warning(f"Upstox 401 Unauthorized: {response.text}")
                    if self._refresh_and_reconnect():
                        token_refreshed = True
                        req_headers["Authorization"] = f"Bearer {self.access_token}"
                        attempt += 1
                        continue
                    else:
                        logger.error("Auto-auth failed to produce a valid token.")
                        return response

                # Case 3: Rate limit (429)
                if response.status_code == 429:
                    wait_time = self.base_backoff_sec * (2**attempt)
                    logger.warning(
                        f"Upstox rate limited (429). Retrying in {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)
                    attempt += 1
                    continue

                # Case 4: Upstox 5xx server errors
                if response.status_code in [500, 502, 503, 504]:
                    wait_time = self.base_backoff_sec * (2**attempt)
                    logger.warning(
                        f"Upstox 5xx server error ({response.status_code}). Retrying in {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)
                    attempt += 1
                    continue

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
                logger.warning(f"Network error: {e}. Retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)

        logger.error(f"Max retries exceeded for URL: {url}")
        return None

    def get_cash_balance(self) -> float:
        """Fetches usable equity cash / available margin balance from Upstox."""
        url = f"{self.base_url}/user/get-funds-and-margin?segment=SEC"
        try:
            res = self._execute_request_with_retry("GET", url)
            if res and res.status_code == 200:
                data = res.json().get("data", {})
                equity_margin = data.get("equity", {})
                cash = (
                    equity_margin.get("available_margin")
                    or equity_margin.get("net")
                    or equity_margin.get("opening_balance")
                    or 0.0
                )
                return float(cash)
            return 0.0
        except Exception as e:
            logger.error(f"Error fetching Upstox cash balance: {e}")
            return 0.0

    def get_holdings(self) -> List[Dict[str, Any]]:
        """Fetches long-term CNC holdings normalized for sync_service."""
        url = f"{self.base_url}/portfolio/long-term-holdings"
        try:
            res = self._execute_request_with_retry("GET", url)
            if res and res.status_code == 200:
                raw_data = res.json().get("data", [])
                normalized = []
                for item in raw_data:
                    ticker = (
                        (
                            item.get("trading_symbol")
                            or item.get("tradingsymbol")
                            or item.get("company_name", "")
                        )
                        .strip()
                        .upper()
                    )

                    normalized.append(
                        {
                            "tradingsymbol": ticker,
                            "symbol": ticker,
                            "quantity": int(item.get("quantity", 0)),
                            "t1_quantity": int(item.get("t1_quantity", 0)),
                            "average_price": float(item.get("average_price", 0.0)),
                            "last_price": float(
                                item.get("last_price") or item.get("close_price") or 0.0
                            ),
                            "pnl": float(item.get("pnl", 0.0)),
                            "exchange": item.get("exchange", "NSE"),
                            "currency": "INR",
                        }
                    )
                return normalized
            return []
        except Exception as e:
            logger.error(f"Error fetching Upstox holdings: {e}")
            return []

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetches short-term positions normalized for sync_service."""
        url = f"{self.base_url}/portfolio/short-term-positions"
        try:
            res = self._execute_request_with_retry("GET", url)
            if res and res.status_code == 200:
                raw_data = res.json().get("data", [])
                normalized = []
                for p in raw_data:
                    ticker = (
                        (p.get("trading_symbol") or p.get("tradingsymbol") or "")
                        .strip()
                        .upper()
                    )
                    normalized.append(
                        {
                            "tradingsymbol": ticker,
                            "symbol": ticker,
                            "quantity": int(p.get("quantity", 0)),
                            "average_price": float(
                                p.get("buy_price") or p.get("average_price") or 0.0
                            ),
                            "last_price": float(p.get("last_price", 0.0)),
                        }
                    )
                return normalized
            return []
        except Exception as e:
            logger.error(f"Error fetching Upstox positions: {e}")
            return []

    def get_trades(self) -> List[Dict[str, Any]]:
        """Fetches executed trades for the day normalized for sync_service."""
        url = f"{self.base_url}/order/trades/get-trades-for-day"
        try:
            res = self._execute_request_with_retry("GET", url)
            if res and res.status_code == 200:
                raw_data = res.json().get("data", [])
                normalized = []
                for t in raw_data:
                    ticker = (
                        (t.get("trading_symbol") or t.get("tradingsymbol") or "")
                        .strip()
                        .upper()
                    )
                    normalized.append(
                        {
                            "tradingsymbol": ticker,
                            "symbol": ticker,
                            "order_id": str(t.get("order_id") or t.get("trade_id")),
                            "trade_id": str(t.get("trade_id") or t.get("order_id")),
                            "transaction_type": (
                                t.get("transaction_type") or "BUY"
                            ).upper(),
                            "quantity": int(
                                t.get("quantity") or t.get("trade_quantity") or 0
                            ),
                            "average_price": float(
                                t.get("average_price") or t.get("trade_price") or 0.0
                            ),
                            "fill_timestamp": t.get("trade_timestamp")
                            or t.get("order_timestamp"),
                            "currency": "INR",
                        }
                    )
                return normalized
            return []
        except Exception as e:
            logger.error(f"Error fetching Upstox trades: {e}")
            return []

    def fetch_historical_daily(
        self, instrument_key: str, days: int = 365
    ) -> pd.DataFrame:
        kolkata_tz = ZoneInfo("Asia/Kolkata")
        now_dt = datetime.now(tz=kolkata_tz)
        to_date = now_dt.strftime("%Y-%m-%d")
        from_date = (now_dt - timedelta(days=days)).strftime("%Y-%m-%d")

        url = f"{self.base_url}/historical-candle/{instrument_key}/day/{to_date}/{from_date}"
        response = self._execute_request_with_retry("GET", url)

        frames = []
        if response and response.status_code == 200:
            candles = response.json().get("data", {}).get("candles", [])
            if candles:
                df_hist = pd.DataFrame(
                    candles,
                    columns=[
                        "timestamp",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "oi",
                    ],
                )
                df_hist["trade_date"] = pd.to_datetime(df_hist["timestamp"]).dt.date
                df_hist.drop(columns=["timestamp", "oi"], inplace=True)
                frames.append(df_hist)

        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        today_date = now_dt.date()
        has_today = not df.empty and (df["trade_date"] == today_date).any()

        # Synthesize from intraday if missing on weekdays
        if not has_today and now_dt.weekday() < 5:
            try:
                df_intra = self.fetch_intraday_candles(
                    instrument_key, interval="5minute"
                )
                if not df_intra.empty:
                    df_intra_sorted = df_intra.sort_values("ts")
                    today_bar = pd.DataFrame(
                        [
                            {
                                "open": float(df_intra_sorted.iloc[0]["open"]),
                                "high": float(df_intra_sorted["high"].max()),
                                "low": float(df_intra_sorted["low"].min()),
                                "close": float(df_intra_sorted.iloc[-1]["close"]),
                                "volume": int(df_intra_sorted["volume"].sum()),
                                "trade_date": today_date,
                            }
                        ]
                    )
                    df = (
                        pd.concat([today_bar, df], ignore_index=True)
                        if not df.empty
                        else today_bar
                    )
            except Exception as e:
                logger.warning(
                    f"Could not synthesize today's daily bar from intraday for {instrument_key}: {e}"
                )

        if not df.empty:
            df = (
                df.drop_duplicates(subset=["trade_date"])
                .sort_values("trade_date")
                .reset_index(drop=True)
            )

        return df

    def place_order(
        self, symbol: str, exchange: str, qty: int, order_type: str, price: float = None
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/order/place"
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
        response = self._execute_request_with_retry("POST", url, json_data=payload)
        return response.json() if response else {"status": "error", "message": "Failed"}

    def fetch_intraday_candles(
        self, instrument_key: str, interval: str = "5minute"
    ) -> pd.DataFrame:
        """Fetches today's live/completed intraday bars from Upstox V3."""
        unit_mins = "5" if "5" in interval else "15"
        url = f"https://api.upstox.com/v3/historical-candle/intraday/{instrument_key}/minutes/{unit_mins}"
        response = self._execute_request_with_retry("GET", url)
        if not response or response.status_code != 200:
            return pd.DataFrame()

        candles = response.json().get("data", {}).get("candles", [])
        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume", "oi"],
        )
        df["ts"] = pd.to_datetime(df["timestamp"])
        if df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize("Asia/Kolkata").dt.tz_convert("UTC")
        else:
            df["ts"] = df["ts"].dt.tz_convert("UTC")

        return df[["ts", "open", "high", "low", "close", "volume"]].drop_duplicates(
            subset=["ts"]
        )

    def fetch_historical_candles(
        self,
        instrument_key: str,
        interval: str = "5minute",
        days: int = 90,
    ) -> pd.DataFrame:
        """
        Fetches historical candles for 'day' or '5minute'.
        For 5m, queries Upstox historical V3 chunks AND combines with the current day's intraday bars.
        Converts all timestamps to UTC for TIMESTAMPTZ storage.
        """
        if interval == "day":
            return self.fetch_historical_daily(instrument_key, days=days)

        unit_mins = "5" if "5" in interval else "15"
        all_candles = []
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days)

        curr_end = end_dt
        while curr_end > start_dt:
            curr_start = max(curr_end - timedelta(days=29), start_dt)
            to_date_str = curr_end.strftime("%Y-%m-%d")
            from_date_str = curr_start.strftime("%Y-%m-%d")

            url = f"https://api.upstox.com/v3/historical-candle/{instrument_key}/minutes/{unit_mins}/{to_date_str}/{from_date_str}"
            response = self._execute_request_with_retry("GET", url)

            if response and response.status_code == 200:
                data = response.json().get("data", {}).get("candles", [])
                if data:
                    all_candles.extend(data)

            curr_end = curr_start - timedelta(days=1)
            time.sleep(0.3)

        frames = []

        # 1. Historical chunked bars
        if all_candles:
            df_hist = pd.DataFrame(
                all_candles,
                columns=["timestamp", "open", "high", "low", "close", "volume", "oi"],
            )
            df_hist["ts"] = pd.to_datetime(df_hist["timestamp"])
            if df_hist["ts"].dt.tz is None:
                df_hist["ts"] = (
                    df_hist["ts"].dt.tz_localize("Asia/Kolkata").dt.tz_convert("UTC")
                )
            else:
                df_hist["ts"] = df_hist["ts"].dt.tz_convert("UTC")
            frames.append(df_hist[["ts", "open", "high", "low", "close", "volume"]])

        # 2. Today's intraday bars
        try:
            df_intra = self.fetch_intraday_candles(
                instrument_key, interval=f"{unit_mins}minute"
            )
            if not df_intra.empty:
                frames.append(df_intra)
        except Exception as e:
            logger.warning(
                f"Could not fetch today's intraday candles for {instrument_key}: {e}"
            )

        if not frames:
            return pd.DataFrame()

        df = (
            pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset=["ts"])
            .sort_values("ts")
        )
        return df

    # Aliases for backward compatibility
    fetch_15min_historical_bars = fetch_historical_candles
    fetch_5min_historical_bars = fetch_historical_candles


upstox_adapter = UpstoxAdapter()
