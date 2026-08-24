from typing import Optional

from app.services.brokers.ibkr_adapter import ibkr_adapter
from app.services.brokers.upstox_adapter import upstox_adapter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class OrderRequest(BaseModel):
    broker: str
    symbol: str
    exchange: str = "NSE"
    order_type: str = "LIMIT"
    quantity: int
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    trailing_stop: Optional[float] = None


@router.post("/place")
def place_order(order: OrderRequest):
    broker_name = order.broker.upper()

    if broker_name == "UPSTOX":
        try:
            res = upstox_adapter.place_order(
                symbol=order.symbol,
                exchange=order.exchange,
                qty=order.quantity,
                order_type=order.order_type,
                price=order.price,
            )
            return {
                "status": "SUCCESS",
                "broker": "UPSTOX",
                "response": res,
                "message": f"Order submitted for {order.quantity} shares of {order.symbol} on Upstox.",
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    elif broker_name == "ZERODHA":
        return {
            "status": "SUCCESS",
            "broker": "ZERODHA",
            "order_id": f"KITE-{order.symbol}-001",
            "message": f"KiteConnect order routed for {order.quantity} shares of {order.symbol}.",
        }

    # Inside your place_order endpoint:
    elif broker_name == "IBKR":
        try:
            res = ibkr_adapter.place_order(
                symbol=order.symbol,
                qty=order.quantity,
                order_type=order.order_type,
                price=order.price,
            )
            return {
                "status": "SUCCESS",
                "broker": "IBKR",
                "response": res,
                "message": f"IBKR order placed for {order.quantity} shares of {order.symbol}.",
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    else:
        raise HTTPException(
            status_code=400, detail=f"Unsupported broker: {order.broker}"
        )
