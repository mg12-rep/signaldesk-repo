import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from app.backtest.enhanced_bb_obv_swing_backtest import (
    BB_OBV_DEFAULT_CONFIG,
)
from app.backtest.enhanced_bb_obv_swing_backtest import (
    compute_strategy_indicators as compute_bb_obv_indicators,
)
from app.backtest.enhanced_bb_obv_swing_backtest import (
    run_backtest as run_bb_obv_simulation,
)
from app.backtest.enhanced_connors_pullback_backtest import (
    CONNORS_DEFAULT_CONFIG,
    compute_connors_indicators,
)
from app.backtest.enhanced_connors_pullback_backtest import (
    run_backtest as run_connors_simulation,
)
from app.backtest.enhanced_minervini_backtest import (
    compute_index_weighted_return,
    compute_market_health,
    get_db_engine,
    load_benchmark_from_db,
    load_universe_from_db,
)
from app.backtest.enhanced_minervini_backtest import (
    compute_summary_stats as compute_minervini_stats,
)
from app.backtest.enhanced_minervini_backtest import (
    run_backtest as run_minervini_simulation,
)
from app.backtest.enhanced_minervini_config import (
    Mode,
    Universe,
)
from app.backtest.enhanced_minervini_config import (
    load_config as load_minervini_cfg,
)
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("backtest_api")
router = APIRouter()

DB_URL = os.getenv("DATABASE_URL", "").replace(
    "postgresql+asyncpg://", "postgresql+psycopg://"
)

# Map UI universe keys to Minervini Universe enum
UNIVERSE_ENUM_MAP = {
    "NIFTY500": Universe.NSE_500,
    "SP500": Universe.SP_500,
    "NASDAQ100": Universe.NASDAQ_100,
}

MARKET_MAPPINGS = {
    "NIFTY500": {"index_symbol_id": 2, "benchmark_symbol_id": 1, "exchange_id": 1},
    "SP500": {"index_symbol_id": 559, "benchmark_symbol_id": 559, "exchange_id": 2},
    "NASDAQ100": {
        "index_symbol_id": 2978,
        "benchmark_symbol_id": 2978,
        "exchange_id": 2,
    },
}

EXCLUDED_CONFIG_KEYS = {
    "db_url",
    "markets",
    "data_dirs",
    "index_files",
    "output_dir",
    "ticker_filter",
    "ticker_filter_file",
}


class BacktestRunRequest(BaseModel):
    strategy: str = "minervini"
    universe: str = "NIFTY500"
    starting_capital: float = 1_000_000.0
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)


@router.get("/config/{strategy}")
def get_strategy_config(strategy: str, universe: str = Query("NIFTY500")):
    strat = strategy.lower().strip()
    u_key = universe.upper().strip()

    if strat == "minervini":
        u_enum = UNIVERSE_ENUM_MAP.get(u_key, Universe.NSE_500)
        try:
            cfg = load_minervini_cfg(mode=Mode.UNIVERSE, universe=u_enum)
            # Exclude db_url, markets, file paths, etc.
            params = {
                k: v
                for k, v in cfg.items()
                if k not in EXCLUDED_CONFIG_KEYS and k != "starting_capital"
            }
            return {
                "strategy": "minervini",
                "universe": u_key,
                "starting_capital": cfg.get("starting_capital", 1_000_000.0),
                "params": params,
                "full_config": cfg,
            }
        except Exception as e:
            logger.error(f"Failed to load Minervini config: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed loading Minervini config: {str(e)}"
            )

    elif strat in ("mean_rev", "bb_obv"):
        bb_path = (
            Path(__file__).resolve().parent.parent
            / "backtest"
            / "config_bb_obv_db.json"
        )
        cfg = dict(BB_OBV_DEFAULT_CONFIG)
        if bb_path.exists():
            with open(bb_path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))

        params = {
            k: v
            for k, v in cfg.items()
            if k not in EXCLUDED_CONFIG_KEYS and k != "starting_capital"
        }
        return {
            "strategy": "mean_rev",
            "universe": u_key,
            "starting_capital": cfg.get("starting_capital", 1_000_000.0),
            "params": params,
            "full_config": cfg,
        }

    elif strat == "connors":
        cfg = dict(CONNORS_DEFAULT_CONFIG)
        connors_path = (
            Path(__file__).resolve().parent.parent
            / "backtest"
            / "config_connors_db.json"
        )
        if connors_path.exists():
            with open(connors_path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))

        params = {
            k: v
            for k, v in cfg.items()
            if k not in EXCLUDED_CONFIG_KEYS and k != "starting_capital"
        }
        return {
            "strategy": "connors",
            "universe": u_key,
            "starting_capital": cfg.get("starting_capital", 1_000_000.0),
            "params": params,
            "full_config": cfg,
        }

    raise HTTPException(status_code=400, detail=f"Unsupported strategy: {strategy}")


@router.post("/run")
def execute_backtest(req: BacktestRunRequest):
    market_cfg = MARKET_MAPPINGS.get(req.universe.upper())
    if not market_cfg:
        raise HTTPException(
            status_code=400, detail=f"Unsupported universe: {req.universe}"
        )

    engine = get_db_engine(DB_URL)
    index_id = market_cfg["index_symbol_id"]
    bench_id = market_cfg["benchmark_symbol_id"]

    universe_data = load_universe_from_db(
        engine=engine,
        index_symbol_id=index_id,
        start_date=req.start_date,
        end_date=req.end_date,
    )
    if not universe_data:
        raise HTTPException(
            status_code=404, detail=f"No historical data found for {req.universe}"
        )

    idx_df = load_benchmark_from_db(engine, bench_id, req.start_date, req.end_date)
    index_return_series = (
        compute_index_weighted_return(idx_df)
        if idx_df is not None and not idx_df.empty
        else None
    )

    strat = req.strategy.lower().strip()

    if strat == "minervini":
        u_enum = UNIVERSE_ENUM_MAP.get(req.universe.upper(), Universe.NSE_500)
        base_cfg = load_minervini_cfg(mode=Mode.UNIVERSE, universe=u_enum)
        base_cfg.update(
            {
                "starting_capital": req.starting_capital,
                "start_date": req.start_date,
                "end_date": req.end_date,
                **req.params,
            }
        )
        market_health = (
            compute_market_health(idx_df, base_cfg)
            if idx_df is not None and not idx_df.empty
            else None
        )
        trade_log, final_cash, bank_balance, eq_df = run_minervini_simulation(
            universe_data, base_cfg, req.universe, index_return_series, market_health
        )
        stats = compute_minervini_stats(
            trade_log, eq_df, base_cfg, final_cash, bank_balance
        )

    elif strat == "connors":
        cfg = dict(CONNORS_DEFAULT_CONFIG)
        cfg.update(
            {
                "starting_capital": req.starting_capital,
                "start_date": req.start_date,
                "end_date": req.end_date,
                **req.params,
            }
        )
        for t, df in universe_data.items():
            universe_data[t] = compute_connors_indicators(df, cfg, index_return_series)
        trade_log, final_cash, bank_balance, eq_df = run_connors_simulation(
            universe_data, cfg, req.universe
        )
        stats = compute_minervini_stats(trade_log, eq_df, cfg, final_cash, bank_balance)

    elif strat in ("mean_rev", "bb_obv"):
        cfg = dict(BB_OBV_DEFAULT_CONFIG)
        cfg.update(
            {
                "starting_capital": req.starting_capital,
                "start_date": req.start_date,
                "end_date": req.end_date,
                **req.params,
            }
        )
        for t, df in universe_data.items():
            universe_data[t] = compute_bb_obv_indicators(df, cfg, index_return_series)
        trade_log, final_cash, bank_balance, eq_df = run_bb_obv_simulation(
            universe_data, cfg, req.universe
        )
        stats = compute_minervini_stats(trade_log, eq_df, cfg, final_cash, bank_balance)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {req.strategy}")

    clean_stats = {
        k: (0.0 if isinstance(v, float) and (v != v) else v) for k, v in stats.items()
    }

    recent_trades = [
        {
            "ticker": t.ticker,
            "entryDate": str(t.entry_date)[:10],
            "entryPrice": round(float(t.entry_price), 2),
            "shares": int(t.shares),
            "exitDate": str(t.exit_date)[:10],
            "exitPrice": round(float(t.exit_price), 2),
            "exitReason": t.exit_reason,
            "pnl": round(float(t.pnl), 2),
            "pnlPct": round(float(t.pnl_pct), 2),
        }
        for t in trade_log[-100:]
    ]

    return {
        "strategy": strat,
        "universe": req.universe,
        "stats": clean_stats,
        "recentTrades": recent_trades,
    }
