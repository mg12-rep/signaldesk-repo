import io
import json
import logging

import pandas as pd
import requests

logger = logging.getLogger("upstox_instruments")

UPSTOX_INSTRUMENTS_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
)


class UpstoxInstrumentRegistry:
    def __init__(self):
        self._symbol_map = {}
        self._is_loaded = False

    def load_instruments(self):
        """Downloads and indexes NSE equity and index instrument keys."""
        try:
            logger.info("Downloading NSE instrument registry from Upstox...")
            response = requests.get(UPSTOX_INSTRUMENTS_URL, timeout=20)
            if response.status_code != 200:
                logger.error(f"Failed to download instruments: {response.text}")
                return

            import gzip

            decompressed_data = gzip.decompress(response.content)
            instruments = json.loads(decompressed_data.decode("utf-8"))

            for item in instruments:
                # Filter for NSE Equities (EQ) and Indices
                seg = item.get("segment")
                sym = item.get("trading_symbol")
                ikey = item.get("instrument_key")

                if sym and ikey:
                    if seg in ["NSE_EQ", "NSE_INDEX"]:
                        self._symbol_map[sym.upper()] = ikey

            self._is_loaded = True
            logger.info(f"Loaded {len(self._symbol_map)} NSE instruments from Upstox.")
        except Exception as e:
            logger.error(f"Error loading instrument registry: {e}")

    def get_instrument_key(self, symbol: str) -> str:
        """Returns instrument_key like 'NSE_EQ|INE002A01018' for 'RELIANCE'."""
        if not self._is_loaded:
            self.load_instruments()
        return self._symbol_map.get(symbol.upper(), None)


upstox_instruments = UpstoxInstrumentRegistry()
