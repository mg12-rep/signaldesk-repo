from typing import List, Optional

from app.screeners.vcp_strategy_config import NSE_CONFIG, SP_CONFIG
from app.screeners.vcp_strategy_screener import run_vcp_scan_db
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ScreenerRunRequest(BaseModel):
    exchange: str = "NSE"  # e.g., "NSE", "NASDAQ", "NYSE"
    benchmark_index: str = "MONIFTY500"  # Used for market health filter
    filter_index: Optional[str] = None  # e.g., "RUSSELL 2000", "NIFTY 50", "S&P 500"
    symbols: Optional[List[str]] = None  # Optional explicit JSON list of tickers
    config_override: Optional[dict] = None
    use_default_config_market: Optional[str] = "NSE"  # e.g., "NSE", "US"


@router.post("/run_vcp")
async def run_screener_endpoint(payload: ScreenerRunRequest):
    cfg = dict(NSE_CONFIG)
    if payload.config_override:
        cfg.update(payload.config_override)
    if payload.use_default_config_market == "NSE":
        cfg.update(NSE_CONFIG)
    elif payload.use_default_config_market == "US":
        cfg.update(SP_CONFIG)

    results = await run_vcp_scan_db(
        cfg=cfg,
        exchange_code=payload.exchange,
        index_symbol=payload.benchmark_index,
        filter_index=payload.filter_index,
        symbols=payload.symbols,
    )
    return {"status": "success", "scanned_symbols_count": len(results or {})}
