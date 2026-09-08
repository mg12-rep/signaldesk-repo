import pandas as pd
from app.screeners.weinstein_screener import run_weinstein_etf_screener

if __name__ == "__main__":
    print("Running Stan Weinstein Stage-2 Screener on US ETFs...")
    results = run_weinstein_etf_screener()

    if not results:
        print("No Stage-2 breakout candidates found or data is still ingesting.")
    else:
        df = pd.DataFrame(results)
        print(f"\nFound {len(df)} Stage-2 Breakout Candidate(s):\n")
        display_cols = [
            "symbol",
            "close",
            "sma30",
            "resistance",
            "volume",
            "avg_volume_10w",
            "mrs",
        ]
        print(df[[c for c in display_cols if c in df.columns]].to_string(index=False))
