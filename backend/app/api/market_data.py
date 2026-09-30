import logging
import pandas as pd
from app.screeners.elder_scanner_75min import (
    compute_elder_impulse,
    engine,
    resample_5m_to_65m,
    resample_5m_to_75m,
)
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

logger = logging.getLogger("market_data_api")
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

        # Fetch 5-minute intraday bars
        intra_q = text("""
            SELECT ts, open, high, low, close, volume 
            FROM market_data_eod_5min 
            WHERE symbol_id = :sid 
            ORDER BY ts ASC;
        """)
        intra_df = pd.read_sql(intra_q, conn, params={"sid": sid})

        # Fetch daily bars across eod and history tables to compute historical PWH & PMH
        daily_q = text("""
            SELECT date, high, low, close 
            FROM (
                SELECT date, high, low, close FROM market_data_eod WHERE symbol_id = :sid
                UNION ALL
                SELECT date, high, low, close FROM market_data_history WHERE symbol_id = :sid
            ) combined
            ORDER BY date ASC;
        """)
        daily_df = pd.read_sql(daily_q, conn, params={"sid": sid})

    if intra_df.empty or len(intra_df) < 10:
        raise HTTPException(status_code=404, detail="Insufficient 5m data for symbol")

    # 1. Resample to 65m (US) or 75m (NSE)
    if is_us:
        df_resampled = resample_5m_to_65m(intra_df, tz=tz)
    else:
        df_resampled = resample_5m_to_75m(intra_df, tz=tz)

    # 2. Build Historical Lookup for Preceding Week & Month Highs
    pwh_map = {}
    pmh_map = {}

    if not daily_df.empty:
        daily_df["date"] = pd.to_datetime(daily_df["date"])
        daily_df = daily_df.sort_values("date").reset_index(drop=True)

        # Assign standard ISO Calendar Week (Monday - Sunday) and Calendar Month
        daily_df["year_week"] = daily_df["date"].dt.strftime("%G-W%V")
        daily_df["year_month"] = daily_df["date"].dt.strftime("%Y-%m")

        # Compute the absolute max High for each completed week and month
        week_highs = daily_df.groupby("year_week")["high"].max().to_dict()
        month_highs = daily_df.groupby("year_month")["high"].max().to_dict()

        sorted_weeks = sorted(week_highs.keys())
        sorted_months = sorted(month_highs.keys())

        # Map each week to its immediately preceding completed week's high
        prior_week_lookup = {}
        for i in range(1, len(sorted_weeks)):
            curr_wk = sorted_weeks[i]
            prev_wk = sorted_weeks[i - 1]
            prior_week_lookup[curr_wk] = round(float(week_highs[prev_wk]), 2)

        # Map each month to its immediately preceding completed month's high
        prior_month_lookup = {}
        for i in range(1, len(sorted_months)):
            curr_mo = sorted_months[i]
            prev_mo = sorted_months[i - 1]
            prior_month_lookup[curr_mo] = round(float(month_highs[prev_mo]), 2)

        for _, row in daily_df.iterrows():
            d_str = row["date"].strftime("%Y-%m-%d")
            w_str = row["year_week"]
            m_str = row["year_month"]

            if w_str in prior_week_lookup:
                pwh_map[d_str] = prior_week_lookup[w_str]
            if m_str in prior_month_lookup:
                pmh_map[d_str] = prior_month_lookup[m_str]

    # 3. Technical indicators
    df_resampled["EMA8"] = df_resampled["Close"].ewm(span=8, adjust=False).mean()
    df_resampled["EMA21"] = df_resampled["Close"].ewm(span=21, adjust=False).mean()
    df_resampled["SMA50"] = df_resampled["Close"].rolling(50, min_periods=10).mean()
    df_resampled["SMA150"] = df_resampled["Close"].rolling(150, min_periods=20).mean()
    df_resampled["SMA200"] = df_resampled["Close"].rolling(200, min_periods=30).mean()
    df_resampled["VolSMA20"] = df_resampled["Volume"].rolling(20, min_periods=1).mean()
    df_resampled = compute_elder_impulse(df_resampled)

    # 4. Format series for Lightweight Charts
    candles = []
    ema8_series = []
    ema21_series = []
    sma50_series = []
    sma150_series = []
    sma200_series = []
    volume_series = []
    vol_sma20_series = []
    pwh_series = []
    pmh_series = []

    for _, row in df_resampled.iterrows():
        bar_dt = pd.to_datetime(row["Date"])
        time_unix = int(bar_dt.timestamp())
        date_str = bar_dt.strftime("%Y-%m-%d")

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

        # Dynamic Preceding Week High
        if date_str in pwh_map:
            pwh_series.append({"time": time_unix, "value": pwh_map[date_str]})

        # Dynamic Preceding Month High
        if date_str in pmh_map:
            pmh_series.append({"time": time_unix, "value": pmh_map[date_str]})

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

        # Volume histogram
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
        "pwh": pwh_series,
        "pmh": pmh_series,
        "ema8": ema8_series,
        "ema21": ema21_series,
        "sma50": sma50_series,
        "sma150": sma150_series,
        "sma200": sma200_series,
        "volume": volume_series,
        "vol_sma20": vol_sma20_series,
    }