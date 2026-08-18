from app.api.screener_api import router as screener_router
from app.api.vcp_screener_api import router as vcp_screener_router
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")

# Register feature sub-routers
api_router.include_router(screener_router)
api_router.include_router(vcp_screener_router)