import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import pandas as pd
from app.services.brokers.base_adapter import BaseBrokerAdapter
from ib_insync import IB, LimitOrder, MarketOrder, Stock

logger = logging.getLogger("ibkr_adapter")


class IBKRAdapter(BaseBrokerAdapter):
    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
        self.host = host
        self.port = port
        self.client_id = client_id
        self._executor = ThreadPoolExecutor(max_workers=1)

    def _run_in_clean_thread(self, target_func):
        """Runs the target function inside a separate OS thread with a dedicated clean event loop."""

        def _worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ib = IB()
            try:
                ib.connect(self.host, self.port, clientId=self.client_id, timeout=10)
                return target_func(ib)
            except Exception as e:
                logger.error(f"IBKR Worker Error: {e}")
                raise
            finally:
                if ib.isConnected():
                    ib.disconnect()
                loop.close()

        future = self._executor.submit(_worker)
        return future.result()

    def get_cash_balance(self) -> float:
        """Fetch available cash balance (USD/Base Currency)."""

        def _fetch(ib: IB) -> float:
            account_values = ib.accountValues()
            for item in account_values:
                if item.tag in (
                    "TotalCashBalance",
                    "AvailableFunds",
                    "CashBalance",
                ) and item.currency in ("USD", "BASE"):
                    return float(item.value)
            for item in account_values:
                if item.tag in ("TotalCashBalance", "AvailableFunds"):
                    return float(item.value)
            return 0.0

        try:
            return self._run_in_clean_thread(_fetch)
        except Exception as e:
            logger.error(f"Error fetching IBKR cash balance: {e}")
            return 0.0

    def get_holdings(self) -> List[Dict[str, Any]]:
        """Fetch portfolio holdings from IBKR."""

        def _fetch(ib: IB) -> List[Dict[str, Any]]:
            portfolio_items = ib.portfolio()
            holdings = []
            for item in portfolio_items:
                if item.position != 0:
                    holdings.append(
                        {
                            "tradingsymbol": item.contract.symbol,
                            "symbol": item.contract.symbol,
                            "quantity": int(item.position),
                            "t1_quantity": 0,
                            "average_price": float(item.averageCost),
                            "last_price": float(item.marketPrice),
                            "pnl": float(item.unrealizedPNL),
                            "exchange": item.contract.primaryExchange
                            or item.contract.exchange,
                            "currency": item.contract.currency or "USD",
                        }
                    )
            return holdings

        try:
            return self._run_in_clean_thread(_fetch)
        except Exception as e:
            logger.error(f"Error fetching IBKR holdings: {e}")
            return []

    def get_positions(self) -> List[Dict[str, Any]]:
        return self.get_holdings()

    def get_trades(self) -> List[Dict[str, Any]]:
        """Fetch executed fills / trades for the current day."""

        def _fetch(ib: IB) -> List[Dict[str, Any]]:
            fills = ib.fills()
            trades = []
            for fill in fills:
                contract = fill.contract
                execution = fill.execution
                trades.append(
                    {
                        "tradingsymbol": contract.symbol,
                        "symbol": contract.symbol,
                        "order_id": str(execution.orderId),
                        "trade_id": str(execution.execId),
                        "transaction_type": "BUY"
                        if execution.side == "BOT"
                        else "SELL",
                        "side": "BUY" if execution.side == "BOT" else "SELL",
                        "quantity": int(execution.shares),
                        "filled_quantity": int(execution.shares),
                        "average_price": float(execution.price),
                        "price": float(execution.price),
                        "fill_timestamp": execution.time,
                        "exchange": contract.exchange,
                        "currency": contract.currency or "USD",
                    }
                )
            return trades

        try:
            return self._run_in_clean_thread(_fetch)
        except Exception as e:
            logger.error(f"Error fetching IBKR trades: {e}")
            return []

    def fetch_historical_daily(
        self, instrument_key: str, days: int = 365
    ) -> pd.DataFrame:
        def _fetch(ib: IB) -> pd.DataFrame:
            contract = Stock(instrument_key, "SMART", "USD")
            ib.qualifyContracts(contract)
            duration = f"{days} D"
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )
            if not bars:
                return pd.DataFrame()

            return pd.DataFrame(
                [
                    {
                        "Date": bar.date,
                        "Open": bar.open,
                        "High": bar.high,
                        "Low": bar.low,
                        "Close": bar.close,
                        "Volume": bar.volume,
                    }
                    for bar in bars
                ]
            )

        try:
            return self._run_in_clean_thread(_fetch)
        except Exception as e:
            logger.error(f"Error fetching historical data for {instrument_key}: {e}")
            return pd.DataFrame()

    def place_order(
        self,
        symbol: str,
        exchange: str = "SMART",
        qty: int = 1,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        def _dispatch(ib: IB) -> Dict[str, Any]:
            contract = Stock(symbol, exchange, "USD")
            ib.qualifyContracts(contract)

            if order_type.upper() == "LIMIT":
                if not price:
                    raise ValueError("Limit orders require a price.")
                order = LimitOrder("BUY" if qty > 0 else "SELL", abs(qty), price)
            else:
                order = MarketOrder("BUY" if qty > 0 else "SELL", abs(qty))

            trade = ib.placeOrder(contract, order)
            ib.sleep(1)
            logger.info(f"✅ IBKR Order Placed: {symbol} | Qty: {qty}")

            return {
                "order_id": str(trade.order.orderId),
                "status": trade.orderStatus.status,
                "broker": "IBKR",
            }

        return self._run_in_clean_thread(_dispatch)

    def fetch_etf_historical_bars(
        self,
        symbol: str,
        duration_str: str = "2 Y",
        bar_size: str = "1 day",
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> pd.DataFrame:
        """
        Fetches adjusted daily OHLCV bars using IBKR's contract qualification.
        Returns a DataFrame with columns: ['date', 'open', 'high', 'low', 'close', 'volume', 'adj_close'].
        """

        def _fetch(ib: IB) -> pd.DataFrame:
            contract = Stock(symbol.upper().strip(), exchange, currency)
            qualified = ib.qualifyContracts(contract)
            if not qualified:
                logger.warning(f"Could not qualify IBKR contract for {symbol}")
                return pd.DataFrame()

            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow="ADJUSTED_LAST",
                useRTH=True,
                formatDate=1,
            )
            if not bars:
                return pd.DataFrame()

            df = pd.DataFrame(
                [
                    {
                        "date": bar.date,
                        "open": float(bar.open),
                        "high": float(bar.high),
                        "low": float(bar.low),
                        "close": float(bar.close),
                        "adj_close": float(bar.close),
                        "volume": int(bar.volume),
                    }
                    for bar in bars
                ]
            )
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df

        try:
            return self._run_in_clean_thread(_fetch)
        except Exception as e:
            logger.error(f"Error fetching IBKR historical bars for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_multiple_etf_bars(
        self, items: List[Dict[str, Any]], delay_seconds: float = 1.2
    ) -> Dict[str, pd.DataFrame]:
        """
        Connects once, requests historical bars with explicit per-contract timeouts,
        and gracefully handles IBKR pacing / timeouts without freezing.
        """

        def _batch(ib: IB) -> Dict[str, pd.DataFrame]:
            results = {}

            # Catch errors like 162 (Pacing violation) or 200 (No security definition)
            def on_error(req_id, error_code, error_string, contract):
                if error_code == 162:
                    logger.warning(
                        f"⚠️ IBKR Pacing Violation (Code 162): {error_string}"
                    )
                elif error_code in (200, 321):
                    logger.warning(
                        f"⚠️ IBKR Contract Error ({error_code}): {error_string}"
                    )

            ib.errorEvent += on_error

            for idx, item in enumerate(items, start=1):
                sym = item["symbol"].upper().strip()
                duration = item.get("duration", "2 Y")
                logger.info(f"[{idx}/{len(items)}] Requesting {sym} ({duration})...")

                try:
                    contract = Stock(sym, "SMART", "USD")
                    qualified = ib.qualifyContracts(contract)
                    if not qualified:
                        logger.warning(f"Could not qualify {sym}, skipping.")
                        continue

                    # Request with explicit duration
                    bars = ib.reqHistoricalData(
                        contract,
                        endDateTime="",
                        durationStr=duration,
                        barSizeSetting="1 day",
                        whatToShow="ADJUSTED_LAST",
                        useRTH=True,
                        formatDate=1,
                        timeout=12,  # Prevents hanging if IBKR drops or fails to return endDateTime
                    )

                    if bars:
                        df = pd.DataFrame(
                            [
                                {
                                    "date": pd.to_datetime(b.date).date(),
                                    "open": float(b.open),
                                    "high": float(b.high),
                                    "low": float(b.low),
                                    "close": float(b.close),
                                    "adj_close": float(b.close),
                                    "volume": int(b.volume),
                                }
                                for b in bars
                            ]
                        )
                        results[sym] = df
                        logger.info(
                            f"[{idx}/{len(items)}] ✅ Received {len(df)} bars for {sym}"
                        )
                    else:
                        logger.warning(
                            f"[{idx}/{len(items)}] Empty bars returned for {sym}"
                        )

                except Exception as e:
                    logger.error(f"[{idx}/{len(items)}] Error fetching {sym}: {e}")

                # Rate limit pacing
                # For first-time seeding with "2 Y", 2.0s gives IBKR breathing room
                sleep_time = (
                    delay_seconds if duration != "2 Y" else max(delay_seconds, 2.0)
                )
                ib.sleep(sleep_time)

            return results

        try:
            return self._run_in_clean_thread(_batch)
        except Exception as err:
            logger.error(f"Failed batch historical data fetch: {err}")
            return {}


ibkr_adapter = IBKRAdapter()
