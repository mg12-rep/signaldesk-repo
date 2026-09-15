import logging
from typing import Any, Dict, List, Optional

from app.db.session import get_db
from app.services.ingest_data import run_eod_pipeline
from app.services.seed_nse_data import get_all_active_symbols, run_full_universe_sync
from app.services.seed_us_data import seed_us_universe_from_db, sync_us_etf_market_data
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/sync", tags=["Market Data Sync"])

logger = logging.getLogger("sync_router")

router = APIRouter()


class SyncResponse(BaseModel):
    status: str
    message: str
    symbol_count: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


# ----------------------------------------------------------------------
# Background Runners
# ----------------------------------------------------------------------
def background_nse_daily_sync(symbols: Optional[List[str]] = None):
    logger.info("🚀 [NSE DAILY] Starting EOD delta ingestion...")
    try:
        if symbols:
            run_eod_pipeline(
                symbols
            )  # Fixed: passed positionally (matches 'symbols: list[str]')
        else:
            # Multi-threaded delta sync for the full active NSE universe
            run_full_universe_sync(full_seed_years=2, max_workers=8)
        logger.info("✅ [NSE DAILY] Ingestion finished successfully.")
    except Exception as e:
        logger.error(f"❌ [NSE DAILY FAILED] Error: {e}", exc_info=True)


def background_nse_15min_sync(csv_path: Optional[str] = None, days: int = 90):
    logger.info(
        f"🚀 [NSE 15MIN] Starting 15-minute ingestion (CSV: {csv_path}, Lookback: {days}d)..."
    )
    try:
        from app.services.seed_nse_data_15min import run_15min_ingestion_pipeline

        run_15min_ingestion_pipeline(csv_path=csv_path, days=days)
        logger.info("✅ [NSE 15MIN] Ingestion finished successfully.")
    except ImportError:
        logger.error(
            "❌ [NSE 15MIN] app.services.ingest_15min_data not implemented yet."
        )
    except Exception as e:
        logger.error(f"❌ [NSE 15MIN FAILED] Error: {e}", exc_info=True)


def background_us_daily_sync():
    logger.info("🚀 [US DAILY] Starting US & Global market data sync via TWS/IBKR...")
    try:
        sync_us_etf_market_data()
        seed_us_universe_from_db()
        logger.info("✅ [US DAILY] S&P 500 & US ETF sync complete.")
    except Exception as e:
        logger.error(f"❌ [US DAILY FAILED] Error: {e}", exc_info=True)


def background_us_15min_sync(csv_path: Optional[str] = None, days: int = 90):
    logger.info(
        f"🚀 [US 15MIN] Starting US 15-minute ingestion (CSV: {csv_path}, Lookback: {days}d)..."
    )
    try:
        from app.services.seed_us_data_15min import run_us_15min_ingestion_pipeline

        run_us_15min_ingestion_pipeline(csv_path=csv_path, days=days)
        logger.info("✅ [US 15MIN] Ingestion finished successfully.")
    except Exception as e:
        logger.error(f"❌ [US 15MIN FAILED] Error: {e}", exc_info=True)


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
    """Syncs daily candles into market_data_all."""
    symbols = get_all_active_symbols()
    count = len(symbols)

    if full_seed:
        background_tasks.add_task(
            run_full_universe_sync, full_seed_years=2, max_workers=workers
        )
        mode = "Full 2-Year Seeding"
    else:
        symbol_list = [s["trading_symbol"] for s in symbols]
        background_tasks.add_task(background_nse_daily_sync, symbols=symbol_list)
        mode = "Daily EOD Delta Sync"

    return SyncResponse(
        status="SUCCESS",
        message=f"{mode} started in background for {count} NSE symbols.",
        symbol_count=count,
    )


@router.post("/nse/15min", response_model=SyncResponse)
def trigger_nse_15min_sync(
    background_tasks: BackgroundTasks,
    csv_path: Optional[str] = Query(
        default="data/selected_stocks.csv",
        description="Path to CSV containing pre-selected stock symbols",
    ),
    days: int = Query(
        default=90,
        ge=1,
        le=90,
        description="Lookback window in days (Upstox limit: 90 days)",
    ),
):
    """Syncs 15-minute intraday candles into market_data_eod_15min for pre-selected NSE stocks."""
    background_tasks.add_task(background_nse_15min_sync, csv_path=csv_path, days=days)
    return SyncResponse(
        status="SUCCESS",
        message=f"15-minute ingestion started in background for stocks in '{csv_path}' ({days} days lookback).",
    )


# ----------------------------------------------------------------------
# US & Global Endpoints
# ----------------------------------------------------------------------
@router.post("/us/daily", response_model=SyncResponse)
@router.post("/us", response_model=SyncResponse)
def trigger_us_sync(background_tasks: BackgroundTasks):
    """Triggers complete US Universe daily pipeline (S&P 500 + US ETFs) via TWS in background."""
    background_tasks.add_task(background_us_daily_sync)
    return SyncResponse(
        status="SUCCESS",
        message="S&P 500 + US ETF daily ingestion started in background via TWS.",
    )


@router.post("/us/15min", response_model=SyncResponse)
def trigger_us_15min_sync(
    background_tasks: BackgroundTasks,
    csv_path: Optional[str] = Query(
        default="data/selected_us_stocks.csv",
        description="Path to CSV containing pre-selected US stock symbols",
    ),
    days: int = Query(
        default=90,
        ge=1,
        le=365,
        description="Lookback window in days (IBKR supports up to 365d for 15-min bars)",
    ),
):
    """Syncs 15-minute intraday candles into market_data_eod_15min for pre-selected US stocks via IBKR."""
    background_tasks.add_task(background_us_15min_sync, csv_path=csv_path, days=days)
    return SyncResponse(
        status="SUCCESS",
        message=f"US 15-minute ingestion started in background for stocks in '{csv_path}' ({days} days lookback).",
    )


@router.post("/us-etfs")
async def sync_us_etfs_endpoint(db: AsyncSession = Depends(get_db)):
    """Synchronous/async direct sync for US ETFs using an active DB session."""
    result = await sync_us_etf_market_data(db)
    return {"status": "success", "result": result}
