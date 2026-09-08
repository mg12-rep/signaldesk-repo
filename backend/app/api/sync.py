import logging

from app.db.session import get_db
from app.services.ingest_data import run_eod_pipeline
from app.services.seed_nse_data import get_all_active_symbols, run_full_universe_sync
from app.services.seed_us_data import seed_us_universe_from_db, sync_us_etf_market_data
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/sync", tags=["sync"])

logger = logging.getLogger("sync_router")
router = APIRouter()


def background_us_sync():
    logger.info("🚀 [IBKR SYNC] Connecting to local TWS session...")
    try:
        logger.info(
            "✅ [IBKR SYNC] Now Syncing US ETFs from data/US_ETF_Tickers.csv..."
        )
        sync_us_etf_market_data()
        logger.info("✅ [IBKR SYNC] US ETF data sync complete.")
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


@router.post("/us-etfs")
async def sync_us_etfs_endpoint(db: AsyncSession = Depends(get_db)):
    result = await sync_us_etf_market_data(db)
    return {"status": "success", "result": result}


def background_nse_sync(universe: list[str]):
    logger.info("🚀 [SYNC TASK STARTED] Ingesting NSE EOD delta bars...")
    try:
        run_eod_pipeline(universe)
        logger.info("✅ [SYNC TASK COMPLETED] NSE EOD ingestion finished successfully.")
    except Exception as e:
        logger.error(f"❌ [SYNC TASK FAILED] NSE ingestion failed: {e}", exc_info=True)
