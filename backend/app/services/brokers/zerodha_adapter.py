import logging
import os
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
from app.services.brokers.base_adapter import BaseBrokerAdapter
from app.services.zerodha_auto_auth import auto_login_zerodha
from dotenv import load_dotenv
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

logger = logging.getLogger("zerodha_adapter")


class ZerodhaAdapter(BaseBrokerAdapter):
    def __init__(self):
        self.kite: Optional[KiteConnect] = None
        self._is_refreshing: bool = False
        self._init_client()

    def _init_client(self, token_override: Optional[str] = None):
        load_dotenv(override=True)
        self.api_key = os.getenv("KITE_API_KEY", "").strip()
        self.access_token = (
            token_override or os.getenv("KITE_ACCESS_TOKEN", "")
        ).strip()

        if self.api_key and self.access_token:
            try:
                client = KiteConnect(api_key=self.api_key)
                client.set_access_token(self.access_token)
                self.kite = client
            except Exception as e:
                logger.error(f"Failed to initialize Kite client: {e}")
                self.kite = None
        else:
            self.kite = None

    def _refresh_and_reconnect(self) -> bool:
        if self._is_refreshing:
            return False
        self._is_refreshing = True
        try:
            logger.info("Refreshing Zerodha token via auto-login...")
            new_token = auto_login_zerodha()
            self._init_client(token_override=new_token)
            return self.kite is not None
        except Exception as e:
            logger.error(f"Failed auto-refreshing Zerodha token: {e}")
            return False
        finally:
            self._is_refreshing = False

    def _call_kite_method(self, method_name: str, *args, **kwargs) -> Any:
        if not self.kite:
            self._init_client()
            if not self.kite and not self._refresh_and_reconnect():
                return None

        try:
            method = getattr(self.kite, method_name)
            return method(*args, **kwargs)
        except (TokenException, Exception) as e:
            err_msg = str(e).lower()
            if (
                isinstance(e, TokenException)
                or "token" in err_msg
                or "403" in err_msg
                or "incorrect `api_key`" in err_msg
            ):
                logger.warning(
                    f"Kite auth error ({e}). Retrying with fresh auto-login..."
                )
                if self._refresh_and_reconnect():
                    try:
                        method = getattr(self.kite, method_name)
                        return method(*args, **kwargs)
                    except Exception as retry_err:
                        logger.error(f"Kite call failed on retry: {retry_err}")
            else:
                logger.error(f"Kite API error on {method_name}: {e}")
            return None

    def get_cash_balance(self) -> float:
        """Fetch available equity cash balance."""
        res = self._call_kite_method("margins", "equity")
        if not res:
            # Fallback to general margins if segment call returned None
            res = self._call_kite_method("margins")

        if not res:
            return 0.0

        try:
            # If segment "equity" was passed, data might be at top-level or under "equity"
            eq = res.get("equity", res)
            avail = eq.get("available", {})

            cash = (
                avail.get("live_balance")
                or avail.get("cash")
                or eq.get("net")
                or avail.get("opening_balance")
                or 0.0
            )
            return float(cash)
        except Exception as e:
            logger.error(f"Error parsing Zerodha cash balance: {e}")
            return 0.0

    def get_holdings(self) -> List[Dict[str, Any]]:
        res = self._call_kite_method("holdings")
        return res if isinstance(res, list) else []

    def get_positions(self) -> List[Dict[str, Any]]:
        res = self._call_kite_method("positions")
        if isinstance(res, dict):
            return res.get("net", [])
        return []

    def get_trades(self) -> List[Dict[str, Any]]:
        res = self._call_kite_method("orders")
        return res if isinstance(res, list) else []

    def place_order(
        self,
        symbol: str,
        exchange: str,
        qty: int,
        order_type: str,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        return (
            self._call_kite_method(
                "place_order",
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=self.kite.TRANSACTION_TYPE_BUY,
                quantity=qty,
                product=self.kite.PRODUCT_CNC,
                order_type=order_type,
                price=price,
            )
            or {}
        )

    def cancel_order(self, order_id: str) -> bool:
        res = self._call_kite_method(
            "cancel_order",
            variety=self.kite.VARIETY_REGULAR,
            order_id=order_id,
        )
        return bool(res)

    def fetch_historical_daily(
        self, instrument_key: str, days: int = 365
    ) -> pd.DataFrame:
        return pd.DataFrame()


zerodha_adapter = ZerodhaAdapter()
