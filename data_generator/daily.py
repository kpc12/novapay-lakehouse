"""Day-by-day simulation (Steps 1.4a-1.4b). Order per day:
master-data changes -> KYC checks -> transactions -> support cases, holdings, credit bureau."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .common import change_seq, write_batch
from .config import GenConfig
from .events import (Bureau, CaseBook, HoldingsBook, is_business_day, is_first_business_day_of_month,
                     run_kyc_checks)
from .state import State, apply_daily_changes
from .transactions import REFUND_LOOKBACK_DAYS, build_transactions, fx_records

SOURCE_OF = {"customers": "core_banking", "accounts": "core_banking",
             "account_holders": "core_banking", "merchants": "acquirer"}


def run_daily(cfg: GenConfig, start: date, end: date) -> list[Path]:
    """Always replay from cfg.start_date (deterministic); write files only for start..end.
    Change and event files are written every day from day 1, even when empty."""
    state = State.initial(cfg)
    holdings = HoldingsBook.initial(cfg, state)
    cases, bureau = CaseBook(), Bureau()
    recent: dict[date, list[dict]] = {}
    paths: list[Path] = []

    def write(source: str, entity: str, d: date, records: list[dict], **kwargs: str) -> None:
        if d >= start:
            paths.append(write_batch(cfg.output_root, source, entity, d, records, **kwargs))

    d = cfg.start_date
    while d <= end:
        if d > cfg.start_date:
            changes = apply_daily_changes(cfg, state, d)
            kyc_events, kyc_changed = run_kyc_checks(cfg, state, d)
            customers = changes["customers"]
            for row, ts in kyc_changed:
                customers.append({"op": "U", "change_seq": change_seq(d, len(customers) + 1),
                                  "change_ts": ts, **row})
            for entity, records in changes.items():
                write(SOURCE_OF[entity], entity, d, records)
            write("reference", "billers", d, [state.billers[k] for k in sorted(state.billers)])
            write("reference", "invest_products", d, [state.products[k] for k in sorted(state.products)])
            write("kyc_vendor", "kyc_checks", d, kyc_events)
        view = state.view()
        records, completed = build_transactions(cfg, view, d, recent)
        recent[d] = completed
        recent.pop(d - timedelta(days=REFUND_LOOKBACK_DAYS), None)
        write("payments", "transactions", d, records, amount_field="amount", currency_field="currency")
        fx = fx_records(cfg, d)
        if fx:
            write("reference", "fx_rates", d, fx)
        bureau.record_bill_payments(records, view, d)
        if d > cfg.start_date:
            declined = {r["customer_id"] for r in records if r["status"] == "declined"}
            write("crm", "support_cases", d, cases.step(cfg, d, view, declined))
        if is_business_day(d):
            write("custodian", "holdings", d, holdings.step(cfg, d, state),
                  amount_field="market_value", currency_field="currency")
        if is_first_business_day_of_month(d):
            write("credit_bureau", "credit_scores", d, bureau.report(cfg, d, view))
        d += timedelta(days=1)
    return paths
