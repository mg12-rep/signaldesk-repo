import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from app.services.brokers.base_adapter import BaseBrokerAdapter
from app.services.brokers.ibkr_adapter import ibkr_adapter
from app.services.brokers.upstox_adapter import upstox_adapter
from app.services.brokers.zerodha_adapter import zerodha_adapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("sync_service")

BROKER_REGISTRY: Dict[str, BaseBrokerAdapter] = {
    "ZERODHA": zerodha_adapter,
    "UPSTOX": upstox_adapter,
    "IBKR": ibkr_adapter,
}

BROKER_CURRENCY: Dict[str, str] = {
    "ZERODHA": "INR",
    "UPSTOX": "INR",
    "IBKR": "USD",
}


def register_broker_adapter(
    broker_name: str, adapter: BaseBrokerAdapter, currency: str = "INR"
):
    """Registers a new broker adapter inheriting from BaseBrokerAdapter."""
    name = broker_name.strip().upper()
    BROKER_REGISTRY[name] = adapter
    BROKER_CURRENCY[name] = currency


async def sync_broker_portfolio(
    db: AsyncSession,
    broker: str = "ZERODHA",
    default_strategy: str = "minervini_vcp",
) -> Dict[str, Any]:
    broker_key = broker.strip().upper()
    adapter = BROKER_REGISTRY.get(broker_key)

    if not adapter:
        raise ValueError(
            f"Unsupported broker: '{broker}'. Available: {list(BROKER_REGISTRY.keys())}"
        )

    currency = BROKER_CURRENCY.get(broker_key, "INR")

    cash_available = adapter.get_cash_balance()
    raw_holdings = adapter.get_holdings()
    raw_positions = adapter.get_positions()
    raw_trades = adapter.get_trades()

    # --- NEW CODE: Persist cash balance into broker_balances table ---
    await db.execute(
        text("""
            INSERT INTO broker_balances (broker, currency, cash_available, updated_at)
            VALUES (:broker, :currency, :cash_available, NOW())
            ON CONFLICT (broker) DO UPDATE SET
                currency = EXCLUDED.currency,
                cash_available = EXCLUDED.cash_available,
                updated_at = NOW();
        """),
        {
            "broker": broker_key,
            "currency": currency,
            "cash_available": round(float(cash_available), 2),
        },
    )
    # -----------------------------------------------------------------
    synced_holdings = 0
    synced_trades = 0
    skipped_symbols: List[str] = []

    # 1. Sync Executed Orders from Broker (Idempotent without ON CONFLICT constraints)
    for tr in raw_trades:
        try:
            trading_sym = (
                (
                    tr.get("tradingsymbol")
                    or tr.get("symbol")
                    or tr.get("instrument_token")
                    or ""
                )
                .strip()
                .upper()
            )

            fill_price = float(
                tr.get("average_price") or tr.get("price") or tr.get("avg_price") or 0.0
            )
            qty = int(tr.get("quantity") or tr.get("filled_quantity") or 0)
            trade_time = (
                tr.get("fill_timestamp")
                or tr.get("order_timestamp")
                or tr.get("trade_time")
            )
            side = (tr.get("transaction_type") or tr.get("side") or "BUY").upper()
            broker_order_id = str(
                tr.get("order_id") or tr.get("trade_id") or ""
            ).strip()

            if not broker_order_id:
                continue

            sym_res = await db.execute(
                text(
                    "SELECT id FROM symbols WHERE UPPER(trading_symbol) = :sym OR UPPER(trading_symbol) = :sym_eq LIMIT 1;"
                ),
                {"sym": trading_sym, "sym_eq": f"{trading_sym}-EQ"},
            )
            sym_row = sym_res.mappings().first()
            if not sym_row:
                continue

            symbol_id = sym_row["id"]

            # Check if this order has already been recorded
            existing = await db.execute(
                text("SELECT id FROM orders WHERE broker_order_id = :boid LIMIT 1;"),
                {"boid": broker_order_id},
            )
            if existing.mappings().first():
                # Already logged; update status and fill price if needed
                await db.execute(
                    text("""
                        UPDATE orders 
                        SET status = 'FILLED',
                            filled_quantity = :qty,
                            average_price = :average_price,
                            updated_at = NOW()
                        WHERE broker_order_id = :boid;
                    """),
                    {"qty": qty, "average_price": fill_price, "boid": broker_order_id},
                )
            else:
                # Fresh order insert
                await db.execute(
                    text("""
                        INSERT INTO orders (
                            symbol_id, broker, strategy, broker_order_id,
                            side, order_type, status, quantity, filled_quantity,
                            average_price, created_at, updated_at
                        )
                        VALUES (
                            :symbol_id, :broker, :strategy, :broker_order_id,
                            :side, 'MARKET', 'FILLED', :qty, :qty,
                            :average_price, COALESCE(:trade_time, NOW()), NOW()
                        );
                    """),
                    {
                        "symbol_id": symbol_id,
                        "broker": broker_key,
                        "strategy": default_strategy,
                        "broker_order_id": broker_order_id,
                        "side": side,
                        "qty": qty,
                        "average_price": fill_price,
                        "trade_time": trade_time,
                    },
                )
            synced_trades += 1
        except Exception as tr_err:
            logger.warning(f"Could not process trade/order: {tr_err}")

    # 2. Normalize and consolidate positions
    active_positions: Dict[str, Dict[str, float]] = {}

    for h in raw_holdings:
        ticker = (
            (h.get("tradingsymbol") or h.get("symbol") or h.get("trading_symbol") or "")
            .strip()
            .upper()
        )
        qty = int(h.get("quantity", 0)) + int(h.get("t1_quantity", 0))
        if qty > 0:
            active_positions[ticker] = {
                "quantity": qty,
                "avg_price": float(h.get("average_price") or h.get("avg_price") or 0.0),
                "ltp": float(
                    h.get("last_price") or h.get("close_price") or h.get("ltp") or 0.0
                ),
            }

    for p in raw_positions:
        ticker = (
            (p.get("tradingsymbol") or p.get("symbol") or p.get("trading_symbol") or "")
            .strip()
            .upper()
        )
        qty = int(p.get("quantity") or p.get("net_quantity") or 0)
        if qty > 0 and ticker not in active_positions:
            active_positions[ticker] = {
                "quantity": qty,
                "avg_price": float(
                    p.get("buy_price")
                    or p.get("average_price")
                    or p.get("avg_price")
                    or 0.0
                ),
                "ltp": float(p.get("last_price") or p.get("ltp") or 0.0),
            }

    active_symbol_ids: List[int] = []

    # 3. Upsert dynamic holdings
    upsert_query = text("""
        INSERT INTO holdings (
            symbol_id, broker, strategy, currency, quantity,
            avg_buy_price, current_price, cost_value, market_value,
            pnl, pnl_pct, entry_date, initial_quantity, updated_at
        )
        VALUES (
            :symbol_id, :broker, :strategy, :currency, :qty,
            :avg_buy_price, :current_price, :cost_val, :market_val,
            :pnl, :pnl_pct, CURRENT_DATE, :qty, NOW()
        )
        ON CONFLICT (symbol_id, broker, strategy) DO UPDATE SET
            quantity = EXCLUDED.quantity,
            avg_buy_price = EXCLUDED.avg_buy_price,
            current_price = EXCLUDED.current_price,
            cost_value = EXCLUDED.cost_value,
            market_value = EXCLUDED.market_value,
            pnl = EXCLUDED.pnl,
            pnl_pct = EXCLUDED.pnl_pct,
            updated_at = NOW()
        RETURNING id, symbol_id, updated_at;
    """)

    for ticker, item in active_positions.items():
        sym_res = await db.execute(
            text(
                "SELECT id FROM symbols WHERE UPPER(trading_symbol) = :sym OR UPPER(trading_symbol) = :sym_eq LIMIT 1;"
            ),
            {"sym": ticker, "sym_eq": f"{ticker}-EQ"},
        )
        sym_row = sym_res.mappings().first()
        if not sym_row:
            logger.warning(
                f"Symbol '{ticker}' not found in symbols table for {broker_key}. Skipping."
            )
            skipped_symbols.append(ticker)
            continue

        symbol_id = sym_row["id"]
        active_symbol_ids.append(symbol_id)

        qty = int(item["quantity"])
        avg_price = float(item["avg_price"])
        current_price = float(item["ltp"]) if item["ltp"] > 0 else avg_price

        cost_val = round(qty * avg_price, 2)
        market_val = round(qty * current_price, 2)
        pnl = round(market_val - cost_val, 2)
        pnl_pct = (
            round(((current_price - avg_price) / avg_price) * 100, 2)
            if avg_price > 0
            else 0.0
        )

        result = await db.execute(
            upsert_query,
            {
                "symbol_id": symbol_id,
                "broker": broker_key,
                "strategy": default_strategy,
                "currency": currency,
                "qty": qty,
                "avg_buy_price": avg_price,
                "current_price": current_price,
                "cost_val": cost_val,
                "market_val": market_val,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            },
        )
        row = result.mappings().first()
        if row:
            synced_holdings += 1

    # 4. Clean up exited positions for THIS broker & strategy only
    # 4. Clean up exited positions (stocks sold on broker set to 0)
    if active_symbol_ids:
        cleanup_query = text("""
            UPDATE holdings 
            SET quantity = 0, market_value = 0, pnl = 0, pnl_pct = 0, updated_at = NOW()
            WHERE broker = :broker 
              AND strategy = :strategy 
              AND NOT (symbol_id = ANY(:active_ids))
              AND quantity > 0;
        """)
        await db.execute(
            cleanup_query,
            {
                "broker": broker_key,
                "strategy": default_strategy,
                "active_ids": list(active_symbol_ids),
            },
        )

    await db.commit()

    return {
        "broker": broker_key,
        "currency": currency,
        "cash_available": cash_available,
        "synced_holdings": synced_holdings,
        "synced_trades": synced_trades,
        "skipped_symbols": skipped_symbols,
    }


async def sync_us_etf_market_data(
    db: AsyncSession,
    csv_path: str = "C:/Work/signaldesk/data/US_ETF_Tickers_2026-09-07.csv",
    delay_between_calls: float = 1.1,
) -> Dict[str, Any]:
    """
    Ingests 2-year daily history for the US ETF list via IBKRAdapter
    and partitions bars into market_data_eod and market_data_history.
    """
    file_path = Path(csv_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Ticker file {csv_path} not found.")

    df_tickers = pd.read_csv(file_path)
    tickers = df_tickers["ticker"].dropna().str.strip().unique().tolist()

    cutoff_date = datetime.now().date() - timedelta(days=365)
    synced_count = 0
    failed_tickers: List[str] = []

    for idx, ticker in enumerate(tickers, start=1):
        sym = ticker.upper()

        # 1. Resolve or create symbol_id with asset_class = 'ETF'
        res = await db.execute(
            text("SELECT id FROM symbols WHERE UPPER(trading_symbol) = :sym LIMIT 1;"),
            {"sym": sym},
        )
        row = res.mappings().first()
        if row:
            symbol_id = row["id"]
            await db.execute(
                text(
                    "UPDATE symbols SET asset_class = 'ETF', is_active = TRUE WHERE id = :id;"
                ),
                {"id": symbol_id},
            )
        else:
            ins = await db.execute(
                text("""
                    INSERT INTO symbols (trading_symbol, name, exchange_id, is_index, asset_class, is_active)
                    VALUES (:sym, :name, 12, FALSE, 'ETF', TRUE)
                    RETURNING id;
                """),
                {"sym": sym, "name": f"{sym} ETF"},
            )
            symbol_id = ins.scalar()

        # 2. Fetch 2 Years via IBKRAdapter
        bars_df = ibkr_adapter.fetch_etf_historical_bars(sym, duration_str="2 Y")
        if bars_df.empty:
            logger.warning(f"[{idx}/{len(tickers)}] No bars received for {sym}")
            failed_tickers.append(sym)
            await asyncio.sleep(delay_between_calls)
            continue

        bars_df["symbol_id"] = symbol_id
        eod_df = bars_df[bars_df["date"] >= cutoff_date]
        hist_df = bars_df[bars_df["date"] < cutoff_date]

        # 3. Upsert into market_data_eod and market_data_history
        upsert_stmt = """
            INSERT INTO {table} (symbol_id, date, open, high, low, close, adj_close, volume)
            VALUES (:symbol_id, :date, :open, :high, :low, :close, :adj_close, :volume)
            ON CONFLICT (symbol_id, date) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, adj_close = EXCLUDED.adj_close, volume = EXCLUDED.volume;
        """

        if not eod_df.empty:
            for record in eod_df.to_dict(orient="records"):
                await db.execute(
                    text(upsert_stmt.format(table="market_data_eod")), record
                )

        if not hist_df.empty:
            for record in hist_df.to_dict(orient="records"):
                await db.execute(
                    text(upsert_stmt.format(table="market_data_history")), record
                )

        await db.commit()
        synced_count += 1
        logger.info(f"[{idx}/{len(tickers)}] Synced {len(bars_df)} bars for {sym}")

        # Pacing delay to avoid IBKR Error 162
        await asyncio.sleep(delay_between_calls)

    return {
        "total_tickers": len(tickers),
        "synced": synced_count,
        "failed": failed_tickers,
    }
