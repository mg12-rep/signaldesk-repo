from app.services.holdings_service import fetch_active_holdings
from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/")
def get_holdings(
    strategy: str = Query(
        "ALL", description="Filter by strategy: MINERVINI, CONNORS, ALL"
    ),
    broker: str = Query(
        "ALL", description="Filter by broker: ZERODHA, UPSTOX, IBKR, ALL"
    ),
):
    return fetch_active_holdings(strategy=strategy, broker=broker)
