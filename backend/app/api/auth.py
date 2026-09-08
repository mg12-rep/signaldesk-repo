from typing import Optional

from app.services.brokers.zerodha_adapter import zerodha_adapter
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/zerodha/callback")
async def zerodha_auth_callback(
    request_token: str = Query(...),
    status: str = Query("success"),
    action: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
):
    if status != "success" or not request_token:
        raise HTTPException(
            status_code=400,
            detail="Zerodha authorization failed or no request token received.",
        )

    # Generate session and store the access token
    try:
        data = zerodha_adapter.generate_session(request_token)
        return {
            "status": "SUCCESS",
            "message": "Zerodha access token generated and persisted successfully.",
            "user_id": data.get("user_id"),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate session: {str(e)}"
        )
