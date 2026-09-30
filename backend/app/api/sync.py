import logging
from typing import Any, Dict, List, Optional

from app.db.session import get_db
from app.services.ingest_data import run_eod_pipeline
from app.services.seed_nse_data import get_nifty500_symbols, run_sync
from app.services.seed_us_data import (
    seed_us_custom_from_file,
    seed_us_universe_from_db,
    sync_us_etf_market_data,
)
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("sync_router")

router = APIRouter(tags=["Market Data Sync"])


class SyncResponse(BaseModel):
    status: str
    message: str
    symbol_count: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


# ----------------------------------------------------------------------
# Background Runners
# ----------------------------------------------------------------------
def background_nse_daily_sync(full_seed: bool = False, workers: int = 8):
    logger.info("🚀 [NSE DAILY] Starting Nifty 500 ingestion...")
    try:
        run_sync(
            mode="nifty500",
            full_seed_years=2 if full_seed else 1,
            max_workers=workers,
        )
        logger.info("✅ [NSE DAILY] Nifty 500 ingestion finished successfully.")
    except Exception as e:
        logger.error(f"❌ [NSE DAILY FAILED] Error: {e}", exc_info=True)


def background_nse_custom_sync(csv_path: str, workers: int = 8):
    logger.info(f"🚀 [NSE CUSTOM] Starting ingestion from file: {csv_path}...")
    try:
        run_sync(
            mode="custom",
            custom_file=csv_path,
            full_seed_years=2,
            max_workers=workers,
        )
        logger.info("✅ [NSE CUSTOM] Ingestion finished successfully.")
    except Exception as e:
        logger.error(f"❌ [NSE CUSTOM FAILED] Error: {e}", exc_info=True)


def background_nse_5min_sync(csv_path: Optional[str] = None, days: int = 60):
    logger.info(
        f"🚀 [NSE 5MIN] Starting 5-minute ingestion (CSV: {csv_path}, Lookback: {days}d)..."
    )
    try:
        from app.services.seed_nse_data_5min import run_5min_ingestion_pipeline

        run_5min_ingestion_pipeline(csv_path=csv_path, days=days)
        logger.info("✅ [NSE 5MIN] Ingestion finished successfully.")
    except ImportError:
        logger.error("❌ [NSE 5MIN] app.services.seed_nse_data_5min not found.")
    except Exception as e:
        logger.error(f"❌ [NSE 5MIN FAILED] Error: {e}", exc_info=True)


def background_us_daily_sync():
    logger.info("🚀 [US DAILY] Starting US & Global market data sync via TWS/IBKR...")
    try:
        seed_us_universe_from_db()
        logger.info("✅ [US DAILY] S&P 500 & US ETF sync complete.")
    except Exception as e:
        logger.error(f"❌ [US DAILY FAILED] Error: {e}", exc_info=True)


def background_us_custom_sync(csv_path: str):
    logger.info(f"🚀 [US CUSTOM] Starting ingestion from file: {csv_path}...")
    try:
        seed_us_custom_from_file(csv_path)
        logger.info("✅ [US CUSTOM] Ingestion finished successfully.")
    except Exception as e:
        logger.error(f"❌ [US CUSTOM FAILED] Error: {e}", exc_info=True)


def background_us_5min_sync(csv_path: Optional[str] = None, days: int = 60):
    logger.info(
        f"🚀 [US 5MIN] Starting US 5-minute ingestion (CSV: {csv_path}, Lookback: {days}d)..."
    )
    try:
        from app.services.seed_us_data_5min import run_us_5min_ingestion_pipeline

        run_us_5min_ingestion_pipeline(csv_path=csv_path, days=days)
        logger.info("✅ [US 5MIN] Ingestion finished successfully.")
    except ImportError:
        logger.error("❌ [US 5MIN] app.services.seed_us_data_5min not found.")
    except Exception as e:
        logger.error(f"❌ [US 5MIN FAILED] Error: {e}", exc_info=True)


# ----------------------------------------------------------------------
# NSE Endpoints
# ----------------------------------------------------------------------
@router.post("/nse/daily", response_model=SyncResponse)
def trigger_nse_daily_sync(
    background_tasks: BackgroundTasks,
    full_seed: bool = Query(
        default=False,
        description="True runs full multi-year seed via Upstox; False runs EOD delta",
    ),
    workers: int = Query(default=8, ge=1, le=16),
):
    """Syncs Nifty 500 daily candles from database registry into market_data_eod."""
    symbols = get_nifty500_symbols()
    count = len(symbols)

    background_tasks.add_task(
        background_nse_daily_sync, full_seed=full_seed, workers=workers
    )

    return SyncResponse(
        status="SUCCESS",
        message=f"Nifty 500 daily ingestion started in background for {count} constituents.",
        symbol_count=count,
    )


@router.post("/nse/custom", response_model=SyncResponse)
def trigger_nse_custom_sync(
    background_tasks: BackgroundTasks,
    csv_path: str = Query(
        default="data/evergreen_filter_nse_stocks.csv",
        description="Path to CSV containing custom NSE symbols",
    ),
    workers: int = Query(default=8, ge=1, le=16),
):
    """Syncs daily candles for custom NSE stocks specified in a local CSV/text file."""
    background_tasks.add_task(
        background_nse_custom_sync, csv_path=csv_path, workers=workers
    )
    return SyncResponse(
        status="SUCCESS",
        message=f"NSE custom daily ingestion started for symbols in '{csv_path}'.",
    )


@router.post("/nse/5min", response_model=SyncResponse)
def trigger_nse_5min_sync(
    background_tasks: BackgroundTasks,
    csv_path: Optional[str] = Query(
        default="data/elder_input_nse_stocks.csv",
        description="Path to CSV containing pre-selected stock symbols",
    ),
    days: int = Query(
        default=60,
        ge=1,
        le=60,
        description="Lookback window in days (Upstox 5m limit: 60 days)",
    ),
):
    """Syncs 5-minute intraday candles into market_data_eod_5min for pre-selected NSE stocks."""
    background_tasks.add_task(background_nse_5min_sync, csv_path=csv_path, days=days)
    return SyncResponse(
        status="SUCCESS",
        message=f"NSE 5-minute ingestion started for stocks in '{csv_path}' ({days} days lookback).",
    )


# ----------------------------------------------------------------------
# US & Global Endpoints
# ----------------------------------------------------------------------
@router.post("/us/daily", response_model=SyncResponse)
@router.post("/us", response_model=SyncResponse)
def trigger_us_sync(background_tasks: BackgroundTasks):
    """Triggers S&P 500 + US ETFs daily pipeline via TWS in background."""
    background_tasks.add_task(background_us_daily_sync)
    return SyncResponse(
        status="SUCCESS",
        message="S&P 500 + US ETF daily ingestion started in background via TWS.",
    )


@router.post("/us-etfs")
async def sync_us_etfs_endpoint(
    csv_path: str = Query(
        default="C:/Work/signaldesk/data/US_ETF_Tickers.csv",
        description="Path to CSV containing ETF tickers",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Direct sync for US ETFs using an active database session."""
    try:
        result = await sync_us_etf_market_data(db, csv_path=csv_path)
        return {
            "status": "success",
            "message": f"US ETFs sync finished: {result.get('synced', 0)} synced, {result.get('skipped', 0)} skipped, {len(result.get('failed', []))} failed.",
            "result": result,
        }
    except Exception as e:
        logger.error(f"❌ Error during US ETF sync: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/us/custom", response_model=SyncResponse)
def trigger_us_custom_sync(
    background_tasks: BackgroundTasks,
    csv_path: str = Query(
        default="data/evergreen_filter_us_stocks.csv",
        description="Path to CSV containing custom US symbols",
    ),
):
    """Syncs daily candles for custom US stocks specified in a local CSV/text file."""
    background_tasks.add_task(background_us_custom_sync, csv_path=csv_path)
    return SyncResponse(
        status="SUCCESS",
        message=f"US custom daily ingestion started for symbols in '{csv_path}'.",
    )


@router.post("/us/5min", response_model=SyncResponse)
def trigger_us_5min_sync(
    background_tasks: BackgroundTasks,
    csv_path: Optional[str] = Query(
        default="data/selected_us_stocks.csv",
        description="Path to CSV containing pre-selected US stock symbols",
    ),
    days: int = Query(
        default=60,
        ge=1,
        le=60,
        description="Lookback window in days for 5-min bars",
    ),
):
    """Syncs 5-minute intraday candles into market_data_eod_5min for pre-selected US stocks via IBKR."""
    background_tasks.add_task(background_us_5min_sync, csv_path=csv_path, days=days)
    return SyncResponse(
        status="SUCCESS",
        message=f"US 5-minute ingestion started for stocks in '{csv_path}' ({days} days lookback).",
    )


class TargetedSyncRequest(BaseModel):
    symbols: List[str]
    market: str = "NSE"


@router.post("/intraday-symbols", response_model=SyncResponse)
def trigger_targeted_intraday_sync(payload: TargetedSyncRequest):
    """
    Synchronously syncs the latest 5m bars for a specific list of tickers
    currently displayed on the frontend results view.
    """
    market_upper = payload.market.upper().strip()
    if market_upper == "NSE":
        from app.services.seed_nse_data_5min import sync_specific_symbols_5min

        result = sync_specific_symbols_5min(payload.symbols)
    elif market_upper == "US":
        from app.services.seed_us_data_5min import sync_specific_us_symbols_5min

        result = sync_specific_us_symbols_5min(payload.symbols)
    else:
        return SyncResponse(
            status="NOT_IMPLEMENTED",
            message=f"Targeted fast sync not configured for market '{payload.market}'.",
            symbol_count=len(payload.symbols),
        )

    return SyncResponse(
        status="SUCCESS",
        message=f"Synced {result['synced']} symbols ({result['skipped']} up to date, {result['failed']} failed).",
        symbol_count=len(payload.symbols),
        details=result,
    )