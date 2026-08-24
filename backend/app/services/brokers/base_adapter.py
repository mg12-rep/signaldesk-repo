from abc import ABC, abstractmethod
from typing import Any, Dict, List

import pandas as pd


class BaseBrokerAdapter(ABC):
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
