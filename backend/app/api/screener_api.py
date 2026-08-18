from typing import Any, Dict, List, Optional

from app.screeners.dynamic_screener import run_market_screener
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/screener", tags=["Screener"])


class ScreenerRequest(BaseModel):
    conditions: List[Dict[str, Any]]
    exchange: Optional[str] = None
    limit: Optional[int] = 100


@router.post("/run")
async def run_screener_endpoint(req: ScreenerRequest):
    try:
        results = await run_market_screener(
            conditions=req.conditions,
            exchange_code=req.exchange,
            limit=req.limit or 100
        )
        return {
            "status": "success",
            "count": len(results),
            "data": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))