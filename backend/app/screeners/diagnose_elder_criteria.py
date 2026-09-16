import argparse
import os
from pathlib import Path
from typing import Optional

import pandas as pd
from app.screeners.elder_scanner_75min import (
    check_timing_sequence,
    compute_elder_impulse,
    resample_15m_to_75m,
    resample_daily_to_weekly,
)
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
sync_db_url = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
engine = create_engine(sync_db_url, pool_size=5, max_overflow=5)


def diagnose_elder_criteria(
    market: str = "NSE",
    csv_path: Optional[str] = None,
):
    market_upper = market.upper().strip()
    tz = "America/New_York" if market_upper == "US" else "Asia/Kolkata"

    if not csv_path:
        csv_path = (
            "C:/Work/signaldesk/data/elder_input_us_stocks.csv"
            if market_upper == "US"
            else "C:/Work/signaldesk/data/elder_input_nse_stocks.csv"
        )

    file_path = Path(csv_path)
    if not file_path.exists():
        print(f"❌ Error: File not found: {csv_path}")
        return

    df_csv = pd.read_csv(file_path)
    col = None
    for c in ["Symbol", "symbol", "trading_symbol", "Ticker", "ticker"]:
        if c in df_csv.columns:
            col = c
            break
    if not col:
        col = df_csv.columns[0]

    tickers = df_csv[col].dropna().astype(str).str.strip().str.upper().tolist()

    counts = {
        "Total in CSV": len(tickers),
        "Symbols with Data in DB": 0,
        "1. Daily MA Stack (Close>8>21>50>150>200)": 0,
        "2. 75m Trend (Close > SMA50)": 0,
        "3. 8 EMA Touch (Low <= EMA8 <= High)": 0,
        "4. Impulse Color GREEN": 0,
        "5. Volume >= 1.25x VolSMA20": 0,
        "6. Timing Sequence (>=3G, >=1B, >=1R)": 0,
        "7. Breakout / Swing Proximity (<3% below)": 0,
    }

    daily_q = text("""
        SELECT date AS "Date", open AS "Open", high AS "High",
               low AS "Low", close AS "Close", volume AS "Volume"
        FROM market_data_all
        WHERE symbol_id = :sid
        ORDER BY date ASC;
    """)

    intra_q = text("""
        SELECT ts, open, high, low, close, volume
        FROM market_data_eod_15min
        WHERE symbol_id = :sid
        ORDER BY ts ASC;
    """)

    with engine.connect() as conn:
        for sym in tickers:
            sid_row = (
                conn.execute(
                    text(
                        "SELECT id FROM symbols WHERE UPPER(trading_symbol) = :sym LIMIT 1;"
                    ),
                    {"sym": sym},
                )
                .mappings()
                .first()
            )

            if not sid_row:
                continue

            sid = sid_row["id"]
            daily_df = pd.read_sql(daily_q, conn, params={"sid": sid})
            intra_df = pd.read_sql(intra_q, conn, params={"sid": sid})

            if len(daily_df) < 200 or len(intra_df) < 25:
                continue

            counts["Symbols with Data in DB"] += 1

            # Prepare Daily & Weekly
            daily_df["Date"] = pd.to_datetime(daily_df["Date"])
            weekly_df = resample_daily_to_weekly(daily_df)

            daily_df["EMA8_D"] = daily_df["Close"].ewm(span=8, adjust=False).mean()
            daily_df["EMA21_D"] = daily_df["Close"].ewm(span=21, adjust=False).mean()
            daily_df["SMA50_D"] = daily_df["Close"].rolling(50).mean()
            daily_df["SMA150_D"] = daily_df["Close"].rolling(150).mean()
            daily_df["SMA200_D"] = daily_df["Close"].rolling(200).mean()

            daily_prep = pd.merge_asof(
                daily_df.sort_values("Date"),
                weekly_df[["Date", "PrevWeek_High"]].sort_values("Date"),
                on="Date",
                direction="backward",
            )

            # Resample 15m to 75m using dynamic timezone
            df_75m = resample_15m_to_75m(intra_df, tz=tz)
            if len(df_75m) < 25:
                continue

            df_75m["EMA8"] = df_75m["Close"].ewm(span=8, adjust=False).mean()
            df_75m["SMA50"] = df_75m["Close"].rolling(50, min_periods=20).mean()
            df_75m["VolSMA20"] = df_75m["Volume"].rolling(20).mean()
            df_75m["SwingHigh"] = df_75m["High"].shift(1).rolling(20).max()
            df_75m = compute_elder_impulse(df_75m)

            df_75m_merge = df_75m.sort_values("Date").copy()
            df_75m_merge["Date"] = pd.to_datetime(
                df_75m_merge["Date"].dt.tz_localize(None)
            ).astype("datetime64[ns]")

            daily_prep_merge = daily_prep.sort_values("Date").copy()
            daily_prep_merge["Date"] = pd.to_datetime(
                daily_prep_merge["Date"].dt.tz_localize(None)
            ).astype("datetime64[ns]")

            merged = pd.merge_asof(
                df_75m_merge,
                daily_prep_merge[
                    [
                        "Date",
                        "EMA8_D",
                        "EMA21_D",
                        "SMA50_D",
                        "SMA150_D",
                        "SMA200_D",
                        "PrevWeek_High",
                    ]
                ],
                on="Date",
                direction="backward",
            ).set_index("Date")

            curr = merged.iloc[-1]
            prior = merged.iloc[:-1]

            # 1. Higher Timeframe Daily stack
            if (
                curr["Close"] > curr["EMA8_D"]
                and curr["EMA8_D"] > curr["EMA21_D"]
                and curr["EMA21_D"] > curr["SMA50_D"]
                and curr["SMA50_D"] > curr["SMA150_D"]
                and curr["SMA150_D"] > curr["SMA200_D"]
            ):
                counts["1. Daily MA Stack (Close>8>21>50>150>200)"] += 1

            # 2. Lower Timeframe 75m trend: Close > SMA50
            if not pd.isna(curr["SMA50"]) and curr["Close"] > curr["SMA50"]:
                counts["2. 75m Trend (Close > SMA50)"] += 1

            # 3. Bar touches 8 EMA
            if curr["Low"] <= curr["EMA8"] <= curr["High"]:
                counts["3. 8 EMA Touch (Low <= EMA8 <= High)"] += 1

            # 4. Elder Impulse Green
            if curr["Impulse_Color"] == "GREEN":
                counts["4. Impulse Color GREEN"] += 1

            # 5. Volume Expansion
            if not pd.isna(curr["VolSMA20"]) and curr["Volume"] >= (
                1.25 * curr["VolSMA20"]
            ):
                counts["5. Volume >= 1.25x VolSMA20"] += 1

            # 6. Timing sequence
            if check_timing_sequence(prior, max_days=14):
                counts["6. Timing Sequence (>=3G, >=1B, >=1R)"] += 1

            # 7. Swing High Proximity
            swing_high = curr["SwingHigh"]
            if (curr["Close"] >= swing_high * 0.97) and (curr["Close"] < swing_high):
                counts["7. Breakout / Swing Proximity (<3% below)"] += 1

            # Add this check right after the individual counts inside the loop:

            meets_trend_and_touch = (
                (
                    curr["Close"]
                    > curr["EMA8_D"]
                    > curr["EMA21_D"]
                    > curr["SMA50_D"]
                    > curr["SMA150_D"]
                    > curr["SMA200_D"]
                )
                and (not pd.isna(curr["SMA50"]) and curr["Close"] > curr["SMA50"])
                and (curr["Low"] <= curr["EMA8"] <= curr["High"])
            )

            if meets_trend_and_touch:
                print(
                    f"Candidate reaching trigger gate: {sym} | Color: {curr['Impulse_Color']} | Vol Ratio: {round(curr['Volume'] / curr['VolSMA20'], 2)}x | Swing Prox: {round((curr['Close'] / curr['SwingHigh'] - 1) * 100, 2)}%"
                )

    print(
        f"\n================== ELDER 75M FUNNEL DIAGNOSTIC ({market_upper}) =================="
    )
    print(f"Target CSV: {csv_path}")
    print(f"Timezone  : {tz}")
    for step, val in counts.items():
        print(f"{step:45}: {val}")
    print("=================================================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Elder 75m criteria diagnostic")
    parser.add_argument(
        "--market", default="NSE", choices=["NSE", "US"], help="Target market"
    )
    parser.add_argument("--csv", default=None, help="Custom CSV path")
    args = parser.parse_args()

    diagnose_elder_criteria(market=args.market, csv_path=args.csv)
