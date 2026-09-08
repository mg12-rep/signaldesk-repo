import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_DIR = Path(__file__).resolve().parent


class Mode(str, Enum):
    UNIVERSE = "UNIVERSE"
    CUSTOM_FILE = "CUSTOM_FILE"


class Universe(str, Enum):
    NSE_500 = "NSE_500"
    NSE_ALL = "NSE_ALL"
    SP_500 = "SP_500"
    NASDAQ_100 = "NASDAQ_100"


class Market(str, Enum):
    NSE = "NSE"
    US = "US"


UNIVERSE_FILE_MAP: dict[Universe, str] = {
    Universe.NSE_500: "config_nse_500.json",
    Universe.NSE_ALL: "config_nse_all.json",
    Universe.SP_500: "config_snp_500.json",
    Universe.NASDAQ_100: "config_nasdaq_100.json",
}

CUSTOM_MARKET_FILE_MAP: dict[Market, str] = {
    Market.NSE: "config_nse_custom.json",
    Market.US: "config_snp_custom.json",
}


def load_config(
    mode: Mode | str,
    universe: Optional[Universe | str] = None,
    market: Optional[Market | str] = None,
) -> Dict[str, Any]:
    """Loads configuration based on execution mode, universe, or market."""
    # Normalize mode to Enum
    if isinstance(mode, str):
        try:
            mode = Mode(mode)
        except ValueError:
            valid_modes = [m.value for m in Mode]
            raise ValueError(f"Invalid mode '{mode}'. Must be one of: {valid_modes}")

    # Branch 1: UNIVERSE
    if mode == Mode.UNIVERSE:
        if not universe:
            raise ValueError(
                "Parameter 'universe' is required when mode is 'UNIVERSE'."
            )

        if isinstance(universe, str):
            try:
                universe = Universe(universe)
            except ValueError:
                valid_universes = [u.value for u in Universe]
                raise ValueError(
                    f"Invalid universe '{universe}'. Must be one of: {valid_universes}"
                )

        filename = UNIVERSE_FILE_MAP[universe]

    # Branch 2: CUSTOM_FILE
    elif mode == Mode.CUSTOM_FILE:
        if not market:
            raise ValueError(
                "Parameter 'market' is required when mode is 'CUSTOM_FILE'."
            )

        if isinstance(market, str):
            try:
                market = Market(market)
            except ValueError:
                valid_markets = [m.value for m in Market]
                raise ValueError(
                    f"Invalid market '{market}'. Must be one of: {valid_markets}"
                )

        filename = CUSTOM_MARKET_FILE_MAP[market]

    # Load and parse file
    file_path = CONFIG_DIR / filename
    if not file_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {file_path.resolve()}")

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)
