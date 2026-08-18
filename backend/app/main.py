import asyncio
from datetime import date, timedelta

from app.api.router import api_router
from app.db.session import AsyncSessionLocal
from app.scripts.archive_eod import archive_old_eod_data
from app.scripts.ingest_market_data import ingest_nse, ingest_us
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI
from sqlalchemy import text

app = FastAPI(title="SignalDesk API")

# Mount all /api/v1 routes
app.include_router(api_router)

scheduler = AsyncIOScheduler()


async def scheduled_nse_ingest():
    end_date = date.today()
    start_date = end_date - timedelta(days=5)
    cutoff_date = end_date - timedelta(days=365)
    await ingest_nse(start_date, end_date, cutoff_date)


async def scheduled_us_ingest():
    end_date = date.today()
    start_date = end_date - timedelta(days=5)
    cutoff_date = end_date - timedelta(days=365)
    await ingest_us(start_date, end_date, cutoff_date)


@app.on_event("startup")
async def startup():
    # Register & Start APScheduler
    # NSE Daily Ingest: Mon-Fri at 18:30 IST
    scheduler.add_job(
        scheduled_nse_ingest,
        CronTrigger(day_of_week="mon-fri", hour=18, minute=30, timezone="Asia/Kolkata"),
        id="nse_daily_ingest",
        replace_existing=True,
    )

    # US Daily Ingest: Tue-Sat at 02:30 IST (Post US close)
    scheduler.add_job(
        scheduled_us_ingest,
        CronTrigger(day_of_week="tue-sat", hour=2, minute=30, timezone="Asia/Kolkata"),
        id="us_daily_ingest",
        replace_existing=True,
    )

    # Weekly Archiver: Saturdays at 02:00 IST
    scheduler.add_job(
        archive_old_eod_data,
        CronTrigger(day_of_week="sat", hour=2, minute=0, timezone="Asia/Kolkata"),
        id="weekly_archiver",
        replace_existing=True,
    )

    scheduler.start()
    print("⏰ APScheduler started successfully.")


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()
    print("⏰ APScheduler stopped.")


@app.get("/health")
async def health_check():
    return {"status": "online", "system": "SignalDesk v1"}


# --- Dynamic Data Sync Helper ---
async def run_smart_nse_sync():
    """Queries max date in market_data_all and syncs missing dates up to today."""
    async with AsyncSessionLocal() as session:
        # Get the latest existing candle date in DB
        res = await session.execute(text("SELECT MAX(date) FROM market_data_all;"))
        max_date = res.scalar()

    end_date = date.today()

    if max_date:
        # Convert to date object if datetime
        start_date = max_date.date() if hasattr(max_date, "date") else max_date
        print(f"📊 Latest DB record found for date: {start_date}")
    else:
        # Fallback if DB is empty
        start_date = end_date - timedelta(days=365)
        print(
            "⚠️ No existing candle records found. Starting initial 1-year historical load."
        )

    # Guard: Don't trigger ingest if already updated today
    if start_date >= end_date:
        print(f"✅ Market data is already up-to-date ({start_date}). No sync required.")
        return

    cutoff_date = end_date - timedelta(days=365)

    print(f"🚀 Triggering NSE Sync: from {start_date} to {end_date}...")
    await ingest_nse(start_date, end_date, cutoff_date)


# --- Dynamic Data Sync Helper ---
async def run_smart_us_sync():
    """Queries max date in market_data_all and syncs missing dates up to today."""
    async with AsyncSessionLocal() as session:
        # Get the latest existing candle date in DB
        res = await session.execute(text("SELECT MAX(date) FROM market_data_all;"))
        max_date = res.scalar()

    end_date = date.today()

    if max_date:
        # Convert to date object if datetime
        start_date = max_date.date() if hasattr(max_date, "date") else max_date
        print(f"📊 Latest DB record found for date: {start_date}")
    else:
        # Fallback if DB is empty
        start_date = end_date - timedelta(days=365)
        print(
            "⚠️ No existing candle records found. Starting initial 1-year historical load."
        )

    # Guard: Don't trigger ingest if already updated today
    if start_date >= end_date:
        print(f"✅ Market data is already up-to-date ({start_date}). No sync required.")
        return

    cutoff_date = end_date - timedelta(days=365)

    print(f"🚀 Triggering US Sync: from {start_date} to {end_date}...")
    await ingest_us(start_date, end_date, cutoff_date)


# --- Manual Trigger Endpoint ---
@app.post("/api/v1/admin/sync-nse-now", tags=["Admin"])
async def trigger_manual_nse_sync(background_tasks: BackgroundTasks):
    """
    Checks the database for the last synced date and syncs up to today in the background.
    """
    background_tasks.add_task(run_smart_nse_sync)
    return {
        "status": "success",
        "message": "Smart NSE market sync task queued in background.",
    }


@app.post("/api/v1/admin/sync-us-now", tags=["Admin"])
async def trigger_manual_us_sync(background_tasks: BackgroundTasks):
    """
    Checks the database for the last synced date and syncs up to today in the background.
    """
    background_tasks.add_task(run_smart_us_sync)
    return {
        "status": "success",
        "message": "Smart US market sync task queued in background.",
    }
