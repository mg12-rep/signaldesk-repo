from typing import Any, Dict, List, Optional

import pandas as pd
from app.db.session import AsyncSessionLocal
from app.services.indicators import compute_all_indicators
from sqlalchemy import text


async def run_market_screener(
    conditions: List[Dict[str, Any]],
    exchange_code: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Runs dynamic screening conditions across active market symbols.
    """
    async with AsyncSessionLocal() as session:
        # 1. Fetch active symbols filtered by exchange
        query_str = """
            SELECT s.id, s.trading_symbol, s.name, e.code as exchange
            FROM symbols s
            JOIN exchanges e ON e.id = s.exchange_id
            WHERE s.is_active = true
        """
        if exchange_code:
            query_str += " AND e.code = :exchange"

        res_symbols = await session.execute(text(query_str), {"exchange": exchange_code} if exchange_code else {})
        symbols = res_symbols.mappings().all()

        matching_stocks = []

        # 2. Iterate and screen each symbol
        for sym in symbols:
            candle_query = text("""
                SELECT date, open, high, low, close, volume
                FROM market_data_all
                WHERE symbol_id = :sym_id
                ORDER BY date ASC
            """)
            res_candles = await session.execute(candle_query, {"sym_id": sym["id"]})
            rows = res_candles.mappings().all()

            if len(rows) < 50:
                continue

            df = pd.DataFrame(rows)
            df_calc = compute_all_indicators(df)
            latest = df_calc.iloc[-1]

            # 3. Evaluate filter conditions on the latest candle
            is_match = True
            for cond in conditions:
                field = cond["field"]
                op = cond["op"]
                target_val = cond["value"]

                if field not in latest:
                    is_match = False
                    break

                actual_val = latest[field]

                # Target comparison against another column (e.g., close > sma_200)
                if isinstance(target_val, str) and target_val in latest:
                    target_val = latest[target_val]

                # SAFEGUARD: Skip if either value is None, NaN, or pd.NA
                if actual_val is None or target_val is None:
                    is_match = False
                    break
                
                if pd.isna(actual_val) or pd.isna(target_val):
                    is_match = False
                    break

                try:
                    # Operator evaluation
                    if op == ">" and not (actual_val > target_val):
                        is_match = False; break
                    elif op == ">=" and not (actual_val >= target_val):
                        is_match = False; break
                    elif op == "<" and not (actual_val < target_val):
                        is_match = False; break
                    elif op == "<=" and not (actual_val <= target_val):
                        is_match = False; break
                    elif op == "==" and not (actual_val == target_val):
                        is_match = False; break
                    elif op == "!=" and not (actual_val != target_val):
                        is_match = False; break
                except TypeError:
                    is_match = False
                    break

            if is_match:
                ltp = float(latest["close"])
                atr = float(latest["atr_14"]) if pd.notna(latest["atr_14"]) else 0.0

                matching_stocks.append({
                    "symbol": sym["trading_symbol"],
                    "name": sym["name"],
                    "exchange": sym["exchange"],
                    "date": str(latest["date"].date()) if hasattr(latest["date"], "date") else str(latest["date"]),
                    "close": ltp,
                    "high_52w": float(latest["high_52w"]) if pd.notna(latest["high_52w"]) else None,
                    "days_since_peak": int(latest["days_since_peak"]) if pd.notna(latest["days_since_peak"]) else 0,
                    "atr_14": round(atr, 2),
                    "kite_trailing_pts": round(2 * atr, 1),
                    "gtt_10pct_floor": round(ltp * 0.90, 1),
                })

                if len(matching_stocks) >= limit:
                    break

        return matching_stocks