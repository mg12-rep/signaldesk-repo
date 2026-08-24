from app.api.backtest import router as backtest_router

# Import feature routers
from app.api.health import router as health_router
from app.api.holdings import router as holdings_router
from app.api.orders import router as orders_router
from app.api.scanner import router as scanner_router

# Import existing screener routers
from app.api.screener_api import router as screener_router
from app.api.sync import router as sync_router
from app.api.vcp_screener_api import router as vcp_screener_router
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")

# Register existing screeners
api_router.include_router(screener_router, prefix="/screener", tags=["Screener"])
api_router.include_router(vcp_screener_router, prefix="/vcp", tags=["VCP Screener"])

# Register core app routes
api_router.include_router(
    health_router, prefix="/market-health", tags=["Market Health"]
)
api_router.include_router(holdings_router, prefix="/holdings", tags=["Holdings"])
api_router.include_router(orders_router, prefix="/orders", tags=["Orders"])
api_router.include_router(scanner_router, prefix="/scanner", tags=["Scanner"])
api_router.include_router(backtest_router, prefix="/backtest", tags=["Backtest"])
api_router.include_router(sync_router, prefix="/sync", tags=["Data Sync"])
