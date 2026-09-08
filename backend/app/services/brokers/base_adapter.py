from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import pandas as pd


class BaseBrokerAdapter(ABC):
    @abstractmethod
    def get_cash_balance(self) -> float:
        """Fetch available cash balance / usable margin."""
        pass

    @abstractmethod
    def get_holdings(self) -> List[Dict[str, Any]]:
        """Fetch CNC / long-term holdings."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch open intraday and derivative positions."""
        pass

    @abstractmethod
    def get_trades(self) -> List[Dict[str, Any]]:
        """Fetch executed trades / fills for the day."""
        pass

    @abstractmethod
    def fetch_historical_daily(
        self, instrument_key: str, days: int = 365
    ) -> pd.DataFrame:
        """Fetch historical daily OHLCV bars as a standard DataFrame."""
        pass

    @abstractmethod
    def place_order(
        self, symbol: str, exchange: str, qty: int, order_type: str, price: float = None
    ) -> Dict[str, Any]:
        """Dispatch an order to the broker."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch current open holdings/positions."""
        pass
