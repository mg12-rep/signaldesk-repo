import numpy as np
import pandas as pd
import pandas_ta as ta


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized calculation of technical indicators using pandas-ta.
    Expects DataFrame sorted chronologically by date with columns:
    ['open', 'high', 'low', 'close', 'volume']
    """
    if df.empty or len(df) < 50:
        return df

    # Ensure index is datetime and sorted chronologically
    df = df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

    # ---------------------------------------------------------
    # 1. TREND / MOVING AVERAGES
    # ---------------------------------------------------------
    df["ema_8"] = ta.ema(df["close"], length=8)
    df["ema_9"] = ta.ema(df["close"], length=9)
    df["ema_21"] = ta.ema(df["close"], length=21)

    df["sma_20"] = ta.sma(df["close"], length=20)
    df["sma_50"] = ta.sma(df["close"], length=50)
    df["sma_150"] = ta.sma(df["close"], length=150)
    df["sma_200"] = ta.sma(df["close"], length=200)

    # Supertrend (10, 3)
    try:
        st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3)
        if st is not None and not st.empty:
            st_col = next((c for c in st.columns if c.startswith("SUPERT_")), None)
            st_dir_col = next((c for c in st.columns if c.startswith("SUPERTd_")), None)

            if st_col:
                df["supertrend"] = st[st_col]
            if st_dir_col:
                df["supertrend_dir"] = st[st_dir_col]  # 1 = Bullish, -1 = Bearish
    except Exception:
        df["supertrend"] = None
        df["supertrend_dir"] = None

    # ADX (14)
    try:
        adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
        if adx_df is not None and not adx_df.empty:
            adx_col = next((c for c in adx_df.columns if c.startswith("ADX_")), None)
            dmp_col = next((c for c in adx_df.columns if c.startswith("DMP_")), None)
            dmn_col = next((c for c in adx_df.columns if c.startswith("DMN_")), None)

            if adx_col:
                df["adx_14"] = adx_df[adx_col]
            if dmp_col:
                df["dmp_14"] = adx_df[dmp_col]
            if dmn_col:
                df["dmn_14"] = adx_df[dmn_col]
    except Exception:
        pass

    # ---------------------------------------------------------
    # 2. MOMENTUM / OSCILLATORS
    # ---------------------------------------------------------
    df["rsi_14"] = ta.rsi(df["close"], length=14)

    # MACD (12, 26, 9)
    try:
        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
            m_col = next((c for c in macd_df.columns if c.startswith("MACD_")), None)
            s_col = next((c for c in macd_df.columns if c.startswith("MACDs_")), None)
            h_col = next((c for c in macd_df.columns if c.startswith("MACDh_")), None)

            if m_col:
                df["macd"] = macd_df[m_col]
            if s_col:
                df["macd_signal"] = macd_df[s_col]
            if h_col:
                df["macd_hist"] = macd_df[h_col]
    except Exception:
        pass

    # Stochastic Oscillator (14, 3, 3)
    try:
        stoch_df = ta.stoch(df["high"], df["low"], df["close"], k=14, d=3, smooth_k=3)
        if stoch_df is not None and not stoch_df.empty:
            k_col = next((c for c in stoch_df.columns if c.startswith("STOCHk_")), None)
            d_col = next((c for c in stoch_df.columns if c.startswith("STOCHd_")), None)

            if k_col:
                df["stoch_k"] = stoch_df[k_col]
            if d_col:
                df["stoch_d"] = stoch_df[d_col]
    except Exception:
        pass

    # CCI (20)
    df["cci_20"] = ta.cci(df["high"], df["low"], df["close"], length=20)

    # ---------------------------------------------------------
    # 3. VOLATILITY / BANDS
    # ---------------------------------------------------------
    # Bollinger Bands (20, 2)
    try:
        bb_df = ta.bbands(df["close"], length=20, std=2)
        if bb_df is not None and not bb_df.empty:
            bbl_col = next((c for c in bb_df.columns if c.startswith("BBL_")), None)
            bbm_col = next((c for c in bb_df.columns if c.startswith("BBM_")), None)
            bbu_col = next((c for c in bb_df.columns if c.startswith("BBU_")), None)
            bbb_col = next((c for c in bb_df.columns if c.startswith("BBB_")), None)

            if bbl_col:
                df["bb_lower"] = bb_df[bbl_col]
            if bbm_col:
                df["bb_middle"] = bb_df[bbm_col]
            if bbu_col:
                df["bb_upper"] = bb_df[bbu_col]
            if bbb_col:
                df["bb_bandwidth"] = bb_df[bbb_col]
    except Exception:
        pass

    # Keltner Channels (20, 2)
    try:
        kc_df = ta.kc(df["high"], df["low"], df["close"], length=20, scalar=2)
        if kc_df is not None and not kc_df.empty:
            kcl_col = next((c for c in kc_df.columns if c.startswith("KCLe_") or c.startswith("KCL_")), None)
            kcu_col = next((c for c in kc_df.columns if c.startswith("KCUe_") or c.startswith("KCU_")), None)

            if kcl_col:
                df["kc_lower"] = kc_df[kcl_col]
            if kcu_col:
                df["kc_upper"] = kc_df[kcu_col]
    except Exception:
        pass

    # ATR (14)
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    # ---------------------------------------------------------
    # 4. VOLUME / FLOW
    # ---------------------------------------------------------
    df["vol_sma_20"] = ta.sma(df["volume"], length=20)
    df["vol_spike"] = df["volume"] > (2.0 * df["vol_sma_20"])

    df["obv"] = ta.obv(df["close"], df["volume"])
    df["cmf_20"] = ta.cmf(df["high"], df["low"], df["close"], df["volume"], length=20)

    # ---------------------------------------------------------
    # 5. STRUCTURAL / BREAKOUTS & MINERVINI PEAK TRACKING
    # ---------------------------------------------------------
    df["high_20d"] = df["high"].rolling(window=20).max()
    df["low_20d"] = df["low"].rolling(window=20).min()
    df["high_52w"] = df["high"].rolling(window=252, min_periods=1).max()
    df["high_52w_97pct"] = df["high_52w"] * 0.97

    # Rolling calculation for days spent since hitting the 52-week peak
    try:
        row_pos = pd.Series(range(len(df)), index=df.index)
        peak_row_pos = df["high"].rolling(window=252, min_periods=1).apply(lambda x: np.argmax(x), raw=True)
        peak_idx = row_pos - (251 - peak_row_pos).clip(lower=0)
        peak_dates = df["date"].iloc[peak_idx.astype(int).values].values
        df["days_since_peak"] = (df["date"] - peak_dates).dt.days
    except Exception:
        df["days_since_peak"] = 0

    # ---------------------------------------------------------
    # 6. HISTORICAL PREVIOUS CANDLE SHIFTS (For Crossovers)
    # ---------------------------------------------------------
    if "macd_hist" in df.columns:
        df["macd_hist_prev"] = df["macd_hist"].shift(1)
    df["rsi_14_prev"] = df["rsi_14"].shift(1)
    df["close_prev"] = df["close"].shift(1)
    df["ema_9_prev"] = df["ema_9"].shift(1)
    df["ema_21_prev"] = df["ema_21"].shift(1)

    return df