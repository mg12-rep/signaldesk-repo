import pandas as pd
from app.screeners.elder_scanner_75min import (
    compute_elder_impulse,
    engine,
    resample_5m_to_65m,
    resample_5m_to_75m,
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
    is_us = target_market == "US"
    tz = "America/New_York" if is_us else "Asia/Kolkata"

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
            FROM market_data_eod_5min 
            WHERE symbol_id = :sid 
            ORDER BY ts ASC;
        """)
        intra_df = pd.read_sql(intra_q, conn, params={"sid": sid})

    if intra_df.empty or len(intra_df) < 10:
        raise HTTPException(status_code=404, detail="Insufficient 5m data for symbol")

    # Resample to 65m (US) or 75m (NSE)
    if is_us:
        df_resampled = resample_5m_to_65m(intra_df, tz=tz)
    else:
        df_resampled = resample_5m_to_75m(intra_df, tz=tz)

    # Technical indicators
    df_resampled["EMA8"] = df_resampled["Close"].ewm(span=8, adjust=False).mean()
    df_resampled["EMA21"] = df_resampled["Close"].ewm(span=21, adjust=False).mean()
    df_resampled["SMA50"] = df_resampled["Close"].rolling(50, min_periods=10).mean()
    df_resampled["SMA150"] = df_resampled["Close"].rolling(150, min_periods=20).mean()
    df_resampled["SMA200"] = df_resampled["Close"].rolling(200, min_periods=30).mean()
    df_resampled["VolSMA20"] = df_resampled["Volume"].rolling(20, min_periods=1).mean()
    df_resampled = compute_elder_impulse(df_resampled)

    # Format data points for lightweight-charts
    candles = []
    ema8_series = []
    ema21_series = []
    sma50_series = []
    sma150_series = []
    sma200_series = []
    volume_series = []
    vol_sma20_series = []

    for _, row in df_resampled.iterrows():
        time_unix = int(pd.to_datetime(row["Date"]).timestamp())
        color_tag = row["Impulse_Color"]
        candle_colors = COLOR_MAP.get(color_tag, COLOR_MAP["BLUE"])
        fill_color = (
            candle_colors["up"]
            if row["Close"] >= row["Open"]
            else candle_colors["down"]
        )

        # Candlestick
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

        # Moving Averages
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

        # Volume histogram (colored semi-transparent by candle direction)
        vol_color = (
            "rgba(34, 197, 94, 0.55)"
            if row["Close"] >= row["Open"]
            else "rgba(239, 68, 68, 0.55)"
        )
        volume_series.append(
            {
                "time": time_unix,
                "value": float(row["Volume"]),
                "color": vol_color,
            }
        )

        # Volume 20-period moving average line
        if not pd.isna(row["VolSMA20"]):
            vol_sma20_series.append(
                {
                    "time": time_unix,
                    "value": round(float(row["VolSMA20"]), 2),
                }
            )

    return {
        "symbol": symbol.upper(),
        "candles": candles,
        "ema8": ema8_series,
        "ema21": ema21_series,
        "sma50": sma50_series,
        "sma150": sma150_series,
        "sma200": sma200_series,
        "volume": volume_series,
        "vol_sma20": vol_sma20_series,
    }
