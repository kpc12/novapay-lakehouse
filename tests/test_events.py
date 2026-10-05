"""Tests for KYC checks, holdings, support cases and credit scores (Step 1.4b)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from helpers import DAYS, SIM_START, alias_map, folder, load, load_all

from data_generator.common import money
from data_generator.events import BAND_LIMITS, is_business_day, is_first_business_day_of_month
from data_generator.state import KEY_CHANGE_DATE, resolve_customer

EVENT_STREAMS = [("kyc_vendor", "kyc_checks"), ("crm", "support_cases")]


def test_event_streams_delivered_every_day(sim):
    for d in DAYS[1:]:
        for source, entity in EVENT_STREAMS:
            assert (folder(sim[1], source, entity, d) / "_manifest.json").exists()


def test_kyc_status_changes_are_backed_by_checks(sim):
    root = sim[1]
    changes: dict = {}
    for d, r in load_all(root, "core_banking", "customers"):
        changes.setdefault(d, []).append(r)
    status: dict[str, str] = {}
    for d in DAYS:
        checks = ({c["customer_id"]: c for c in load(folder(root, "kyc_vendor", "kyc_checks", d))}
                  if d > SIM_START else {})
        for r in changes.get(d, []):
            prev = status.get(r["old_customer_id"] or r["customer_id"])
            if prev is not None and prev != r["kyc_status"]:
                assert (r["kyc_status"] == "verified") == (checks[r["customer_id"]]["result"] == "pass")
            status[r["customer_id"]] = r["kyc_status"]


def test_holdings_on_business_days_with_consistent_values(sim):
    root = sim[1]
    old_ids = set(alias_map(root))
    for d in DAYS:
        f = folder(root, "custodian", "holdings", d)
        assert f.exists() == is_business_day(d)
        if not f.exists():
            continue
        for h in load(f):
            assert Decimal(h["units"]) > 0
            assert h["market_value"] == money(Decimal(h["units"]) * Decimal(h["price"]))
            if d >= KEY_CHANGE_DATE:
                assert h["customer_id"] not in old_ids


def test_support_case_lifecycle(sim):
    history: dict[str, list[dict]] = {}
    for _, r in load_all(sim[1], "crm", "support_cases"):
        history.setdefault(r["case_id"], []).append(r)
    order = ["opened", "in_progress", "resolved"]
    for rows in history.values():
        assert rows[0]["op"] == "I" and all(r["op"] == "U" for r in rows[1:])
        assert [r["status"] for r in rows] == order[:len(rows)]
        last = rows[-1]
        times = [t for t in (last["opened_ts"], last["first_response_ts"], last["resolved_ts"]) if t]
        assert times == sorted(times)


def test_credit_scores_monthly_and_consistent(sim):
    root = sim[1]
    alias = alias_map(root)
    report_days = [d for d in DAYS if folder(root, "credit_bureau", "credit_scores", d).exists()]
    assert report_days == [d for d in DAYS if is_first_business_day_of_month(d)]
    late: dict[tuple[str, str], int] = {}
    for d in DAYS:
        for t in load(folder(root, "payments", "transactions", d)):
            if t["transaction_type"] == "bill_payment":
                days_late = (d - date.fromisoformat(t["due_date"])).days
                if days_late > 0:
                    key = (resolve_customer(alias, t["customer_id"]), f"{d:%Y-%m}")
                    late[key] = max(late.get(key, 0), days_late)
    for d in report_days:
        month = f"{d.replace(day=1) - timedelta(days=1):%Y-%m}"
        for s in load(folder(root, "credit_bureau", "credit_scores", d)):
            assert s["report_month"] == month
            assert 1 <= s["score"] <= 999
            assert s["risk_band"] == next((b for limit, b in BAND_LIMITS if s["score"] >= limit), "E")
            if month >= f"{SIM_START:%Y-%m}":
                key = (resolve_customer(alias, s["customer_id"]), month)
                assert s["days_past_due_max"] == late.get(key, 0)
