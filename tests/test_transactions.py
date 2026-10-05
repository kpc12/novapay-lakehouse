"""Transaction tests on the simulated window. Run from the repo root: python -m pytest"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from helpers import DAYS, SIM_START, alias_map, folder, load, load_all, small_cfg

from data_generator.common import money
from data_generator.daily import run_daily
from data_generator.state import resolve_customer
from data_generator.transactions import CURRENCY_BY_COUNTRY, is_fx_publication_day

VILNIUS = ZoneInfo("Europe/Vilnius")
OUTGOING = {"purchase", "bill_payment", "transfer_out"}


@pytest.fixture(scope="module")
def txns(sim):
    return {d: load(folder(sim[1], "payments", "transactions", d)) for d in DAYS}


def test_deterministic(tmp_path):
    for sub in ("a", "b"):
        run_daily(small_cfg(tmp_path / sub), SIM_START, SIM_START)
    rel = folder(tmp_path, "payments", "transactions", SIM_START).relative_to(tmp_path) / "part-0001.jsonl"
    assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes()


def test_transaction_ids_unique(txns):
    ids = [r["transaction_id"] for rows in txns.values() for r in rows]
    assert len(ids) == len(set(ids))


def test_partition_is_vilnius_business_date(txns):
    for d, rows in txns.items():
        for r in rows:
            utc = datetime.strptime(r["event_ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            assert utc.astimezone(VILNIUS).date() == d


def test_refunds_reference_earlier_completed_purchases(sim, txns):
    alias = alias_map(sim[1])
    purchases = {r["transaction_id"]: (d, r) for d, rows in txns.items()
                 for r in rows if r["transaction_type"] == "purchase"}
    for d, rows in txns.items():
        for r in (x for x in rows if x["transaction_type"] == "refund"):
            orig_day, orig = purchases[r["original_transaction_id"]]
            assert orig_day < d and orig["status"] == "completed"
            assert resolve_customer(alias, orig["customer_id"]) == resolve_customer(alias, r["customer_id"])
            for field in ("account_id", "currency", "merchant_id", "payment_method"):
                assert r[field] == orig[field]
            assert Decimal(r["amount"]) <= Decimal(orig["amount"])


def test_payment_method_matches_account_type(sim, txns):
    kinds = {r["account_id"]: r["account_type"]
             for _, r in load_all(sim[1], "core_banking", "accounts") if r["op"] == "I"}
    allowed = {"credit_card": {"credit_card"}, "debit_card": {"current"}, "bank_transfer": {"current"},
               "mobile_wallet": {"current", "credit_card"}}
    for rows in txns.values():
        for r in rows:
            assert kinds[r["account_id"]] in allowed[r["payment_method"]]


def test_currency_matches_merchant_country(sim, txns):
    country = {r["merchant_id"]: r["country"] for _, r in load_all(sim[1], "acquirer", "merchants")}
    for rows in txns.values():
        for r in rows:
            if r["merchant_id"] is None:
                assert r["currency"] == "EUR"
            else:
                assert r["currency"] == CURRENCY_BY_COUNTRY[country[r["merchant_id"]]]
                if country[r["merchant_id"]] != "LT":
                    assert r["channel"] == "online"


def test_expired_kyc_customers_make_no_outgoing_payments(sim, txns):
    day0 = load(folder(sim[1], "core_banking", "customers", SIM_START))
    expired = {c["customer_id"] for c in day0 if c["kyc_status"] == "expired"}
    for rows in txns.values():
        assert not [r for r in rows if r["transaction_type"] in OUTGOING and r["customer_id"] in expired]


def test_bill_payment_dates_and_salary_weekdays(txns):
    for d, rows in txns.items():
        for r in rows:
            if r["transaction_type"] == "bill_payment":
                assert -5 <= (d - date.fromisoformat(r["due_date"])).days <= 10
            if r["transaction_type"] == "salary_in":
                assert d.weekday() < 5


def test_counterparty_iban_valid(txns):
    for rows in txns.values():
        for r in (x for x in rows if x["transaction_type"] == "transfer_out"):
            iban = r["counterparty_iban"]
            assert len(iban) == 20 and iban.startswith("LT")
            assert int(iban[4:] + "2129" + iban[2:4]) % 97 == 1


def test_manifest_totals_per_currency(sim, txns):
    for d, rows in txns.items():
        manifest = json.loads((folder(sim[1], "payments", "transactions", d) / "_manifest.json").read_text())
        totals: dict[str, Decimal] = {}
        for r in rows:
            totals[r["currency"]] = totals.get(r["currency"], Decimal("0")) + Decimal(r["amount"])
        assert manifest["record_count"] == len(rows)
        assert manifest["amount_totals"] == {k: money(v) for k, v in sorted(totals.items())}


def test_fx_files_only_on_publication_days(sim):
    for d in DAYS:
        f = folder(sim[1], "reference", "fx_rates", d)
        assert f.exists() == is_fx_publication_day(d)
        if f.exists():
            rates = load(f)
            assert {r["currency"] for r in rates} == {"GBP", "PLN", "SEK", "USD"}
            assert all(Decimal(r["rate"]) > 0 for r in rates)
