import logging

from app.services.ingest_data import run_eod_pipeline
from app.services.seed_nse_data import get_all_active_symbols, run_full_universe_sync
from app.services.seed_us_data import seed_us_universe_from_db
from fastapi import APIRouter, BackgroundTasks

logger = logging.getLogger("sync_router")
router = APIRouter()


def background_us_sync():
    logger.info("🚀 [IBKR SYNC] Connecting to local TWS session...")
    try:
        seed_us_universe_from_db()
        logger.info("✅ [IBKR SYNC] US & Global universe data sync complete.")
    except Exception as e:
        logger.error(f"❌ [IBKR SYNC FAILED] Error: {e}", exc_info=True)


@router.post("/us")
def trigger_us_sync(background_tasks: BackgroundTasks):
    background_tasks.add_task(seed_us_universe_from_db)
    return {
        "status": "SUCCESS",
        "message": "S&P 500 + US ETF ingestion started in background via TWS.",
    }


@router.post("/nse")
def trigger_nse_sync(background_tasks: BackgroundTasks):
    symbols = get_all_active_symbols()
    background_tasks.add_task(run_full_universe_sync)
    return {
        "status": "SUCCESS",
        "message": f"Full NSE Universe sync started in background for {len(symbols)} symbols.",
    }


def background_nse_sync(universe: list[str]):
    logger.info("🚀 [SYNC TASK STARTED] Ingesting NSE EOD delta bars...")
    try:
        run_eod_pipeline(universe)
        logger.info("✅ [SYNC TASK COMPLETED] NSE EOD ingestion finished successfully.")
    except Exception as e:
        logger.error(f"❌ [SYNC TASK FAILED] NSE ingestion failed: {e}", exc_info=True)
