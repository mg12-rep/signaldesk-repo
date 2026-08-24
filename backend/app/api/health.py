from app.services.market_health import get_market_regime
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def market_health():
    return get_market_regime()
