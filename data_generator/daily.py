"""Day-by-day simulation: master-data changes first, then transactions (Step 1.4a)."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .common import write_batch
from .config import GenConfig
from .state import State, apply_daily_changes
from .transactions import REFUND_LOOKBACK_DAYS, build_transactions, fx_records

SOURCE_OF = {"customers": "core_banking", "accounts": "core_banking",
             "account_holders": "core_banking", "merchants": "acquirer"}


def run_daily(cfg: GenConfig, start: date, end: date) -> list[Path]:
    """Always replay from cfg.start_date (deterministic); write files only for start..end.
    Change files are written every day, even when empty: an empty file + manifest means
    'no changes today', which is different from 'file missing'."""
    state = State.initial(cfg)
    recent: dict[date, list[dict]] = {}
    paths: list[Path] = []
    root = cfg.output_root
    d = cfg.start_date
    while d <= end:
        changes = apply_daily_changes(cfg, state, d) if d > cfg.start_date else None
        records, completed = build_transactions(cfg, state.view(), d, recent)
        recent[d] = completed
        recent.pop(d - timedelta(days=REFUND_LOOKBACK_DAYS), None)
        if d >= start:
            if changes is not None:
                for entity, recs in changes.items():
                    paths.append(write_batch(root, SOURCE_OF[entity], entity, d, recs))
                paths.append(write_batch(root, "reference", "billers", d,
                                         [state.billers[k] for k in sorted(state.billers)]))
                paths.append(write_batch(root, "reference", "invest_products", d,
                                         [state.products[k] for k in sorted(state.products)]))
            paths.append(write_batch(root, "payments", "transactions", d, records,
                                     amount_field="amount", currency_field="currency"))
            fx = fx_records(cfg, d)
            if fx:
                paths.append(write_batch(root, "reference", "fx_rates", d, fx))
        d += timedelta(days=1)
    return paths
