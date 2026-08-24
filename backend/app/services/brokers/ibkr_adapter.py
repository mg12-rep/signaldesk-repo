import logging
from typing import Any, Dict, Optional

from ib_insync import IB, LimitOrder, MarketOrder, Stock

logger = logging.getLogger("ibkr_adapter")


class IBKRAdapter:
    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()

    def _connect(self):
        if not self.ib.isConnected():
            try:
                self.ib.connect(self.host, self.port, clientId=self.client_id)
            except Exception as e:
                logger.error(
                    f"IBKR Connection failed: {e}. Ensure TWS/Gateway is running."
                )
                raise

    def place_order(
        self,
        symbol: str,
        qty: int,
        order_type: str = "LIMIT",
        price: Optional[float] = None,
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Dict[str, Any]:
        self._connect()
        contract = Stock(symbol, exchange, currency)
        self.ib.qualifyContracts(contract)

        if order_type.upper() == "LIMIT":
            if not price:
                raise ValueError("Limit orders require a price.")
            order = LimitOrder("BUY" if qty > 0 else "SELL", abs(qty), price)
        else:
            order = MarketOrder("BUY" if qty > 0 else "SELL", abs(qty))

        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(1)  # Allow order to broadcast
        logger.info(f"✅ IBKR Order Placed: {symbol} | Qty: {qty}")

        return {
            "order_id": trade.order.orderId,
            "status": trade.orderStatus.status,
            "broker": "IBKR",
        }


ibkr_adapter = IBKRAdapter()
