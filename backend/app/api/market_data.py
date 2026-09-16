import pandas as pd
from app.screeners.elder_scanner_75min import (
    compute_elder_impulse,
    engine,
    resample_15m_to_75m,
)
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

router = APIRouter()

COLOR_MAP = {
    "GREEN": {"up": "#22c55e", "down": "#16a34a"},
    "RED": {"up": "#ef4444", "down": "#dc2626"},
    "BLUE": {"up": "#38bdf8", "down": "#0284c7"},
}


@router.get("/chart-data/75min")
def get_elder_75min_chart_data(
    symbol: str = Query(..., description="Stock symbol (e.g., CF, RELIANCE)"),
    market: str = Query("US", description="NSE or US"),
):
    target_market = market.upper().strip()
    tz = "America/New_York" if target_market == "US" else "Asia/Kolkata"

    with engine.connect() as conn:
        sid_row = (
            conn.execute(
                text(
                    "SELECT id FROM symbols WHERE UPPER(trading_symbol) = :sym LIMIT 1;"
                ),
                {"sym": symbol.upper().strip()},
            )
            .mappings()
            .first()
        )

        if not sid_row:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

        sid = sid_row["id"]
        intra_q = text("""
            SELECT ts, open, high, low, close, volume 
            FROM market_data_eod_15min 
            WHERE symbol_id = :sid 
            ORDER BY ts ASC;
        """)
        intra_df = pd.read_sql(intra_q, conn, params={"sid": sid})

    if intra_df.empty or len(intra_df) < 10:
        raise HTTPException(status_code=404, detail="Insufficient 15m data for symbol")

    # Resample to 75m and compute indicators
    df_75m = resample_15m_to_75m(intra_df, tz=tz)
    df_75m["EMA8"] = df_75m["Close"].ewm(span=8, adjust=False).mean()
    df_75m["EMA21"] = df_75m["Close"].ewm(span=21, adjust=False).mean()
    df_75m["SMA50"] = df_75m["Close"].rolling(50, min_periods=10).mean()
    df_75m["SMA150"] = df_75m["Close"].rolling(150, min_periods=20).mean()
    df_75m["SMA200"] = df_75m["Close"].rolling(200, min_periods=30).mean()
    df_75m = compute_elder_impulse(df_75m)

    # Format data points for lightweight-charts
    candles = []
    ema8_series = []
    ema21_series = []
    sma50_series = []
    sma150_series = []
    sma200_series = []

    for _, row in df_75m.iterrows():
        # Lightweight-charts accepts UNIX timestamps (seconds)
        time_unix = int(pd.to_datetime(row["Date"]).timestamp())
        color_tag = row["Impulse_Color"]
        candle_colors = COLOR_MAP.get(color_tag, COLOR_MAP["BLUE"])
        fill_color = (
            candle_colors["up"]
            if row["Close"] >= row["Open"]
            else candle_colors["down"]
        )

        candles.append(
            {
                "time": time_unix,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "color": fill_color,
                "borderColor": fill_color,
                "wickColor": fill_color,
            }
        )

        if not pd.isna(row["EMA8"]):
            ema8_series.append(
                {"time": time_unix, "value": round(float(row["EMA8"]), 2)}
            )
        if not pd.isna(row["EMA21"]):
            ema21_series.append(
                {"time": time_unix, "value": round(float(row["EMA21"]), 2)}
            )
        if not pd.isna(row["SMA50"]):
            sma50_series.append(
                {"time": time_unix, "value": round(float(row["SMA50"]), 2)}
            )
        if not pd.isna(row["SMA150"]):
            sma150_series.append(
                {"time": time_unix, "value": round(float(row["SMA150"]), 2)}
            )
        if not pd.isna(row["SMA200"]):
            sma200_series.append(
                {"time": time_unix, "value": round(float(row["SMA200"]), 2)}
            )

    return {
        "symbol": symbol.upper(),
        "candles": candles,
        "ema8": ema8_series,
        "ema21": ema21_series,
        "sma50": sma50_series,
        "sma150": sma150_series,
        "sma200": sma200_series,
    }
