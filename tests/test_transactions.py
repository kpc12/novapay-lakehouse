"""Tests for daily transactions and FX rates. Run from the repo root: python -m pytest"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from data_generator.common import money
from data_generator.config import GenConfig
from data_generator.transactions import (CURRENCY_BY_COUNTRY, build_context, generate_range,
                                         is_fx_publication_day)

START, END = date(2026, 9, 1), date(2026, 9, 14)
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]
VILNIUS = ZoneInfo("Europe/Vilnius")
OUTGOING = {"purchase", "bill_payment", "transfer_out"}


def _cfg(root: Path) -> GenConfig:
    return replace(GenConfig(), output_root=root, n_customers=300, n_merchants=50)


def _folder(root: Path, source: str, entity: str, d: date) -> Path:
    return root / source / entity / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}"


def _load(folder: Path) -> list[dict]:
    return [json.loads(x) for x in (folder / "part-0001.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def gen(tmp_path_factory):
    root = tmp_path_factory.mktemp("txn")
    cfg = _cfg(root)
    generate_range(cfg, START, END)
    txns = {d: _load(_folder(root, "payments", "transactions", d)) for d in DAYS}
    return cfg, root, txns


def test_deterministic(tmp_path):
    for sub in ("a", "b"):
        generate_range(_cfg(tmp_path / sub), START, START)
    f = Path("payments/transactions/2026/09/01/part-0001.jsonl")
    assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes()


def test_transaction_ids_unique(gen):
    ids = [r["transaction_id"] for rows in gen[2].values() for r in rows]
    assert len(ids) == len(set(ids))


def test_partition_is_vilnius_business_date(gen):
    for d, rows in gen[2].items():
        for r in rows:
            utc = datetime.strptime(r["event_ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            assert utc.astimezone(VILNIUS).date() == d


def test_refunds_reference_earlier_completed_purchases(gen):
    purchases = {r["transaction_id"]: (d, r) for d, rows in gen[2].items()
                 for r in rows if r["transaction_type"] == "purchase"}
    for d, rows in gen[2].items():
        for r in (x for x in rows if x["transaction_type"] == "refund"):
            orig_day, orig = purchases[r["original_transaction_id"]]
            assert orig_day < d and orig["status"] == "completed"
            for field in ("customer_id", "account_id", "currency", "merchant_id"):
                assert r[field] == orig[field]
            assert Decimal(r["amount"]) <= Decimal(orig["amount"])


def test_payment_method_matches_account(gen):
    ctx = build_context(gen[0])
    for rows in gen[2].values():
        for r in rows:
            cid, method = r["customer_id"], r["payment_method"]
            if method == "credit_card":
                assert r["account_id"] == ctx.card_acc[cid]
            elif method == "mobile_wallet":
                assert r["account_id"] in {ctx.current_acc[cid], ctx.card_acc.get(cid)}
            else:
                assert r["account_id"] == ctx.current_acc[cid]


def test_currency_matches_merchant_country(gen):
    country = {m["merchant_id"]: m["country"] for m in build_context(gen[0]).merchants}
    for rows in gen[2].values():
        for r in rows:
            if r["merchant_id"] is None:
                assert r["currency"] == "EUR"
            else:
                assert r["currency"] == CURRENCY_BY_COUNTRY[country[r["merchant_id"]]]
                if country[r["merchant_id"]] != "LT":
                    assert r["channel"] == "online"


def test_expired_kyc_customers_make_no_outgoing_payments(gen):
    expired = {c["customer_id"] for c in build_context(gen[0]).customers if c["kyc_status"] == "expired"}
    for rows in gen[2].values():
        assert not [r for r in rows if r["transaction_type"] in OUTGOING and r["customer_id"] in expired]


def test_bill_payment_dates_and_salary_weekdays(gen):
    for d, rows in gen[2].items():
        for r in rows:
            if r["transaction_type"] == "bill_payment":
                assert -5 <= (d - date.fromisoformat(r["due_date"])).days <= 10
            if r["transaction_type"] == "salary_in":
                assert d.weekday() < 5


def test_counterparty_iban_valid(gen):
    for rows in gen[2].values():
        for r in (x for x in rows if x["transaction_type"] == "transfer_out"):
            iban = r["counterparty_iban"]
            assert len(iban) == 20 and iban.startswith("LT")
            assert int(iban[4:] + "2129" + iban[2:4]) % 97 == 1


def test_manifest_totals_per_currency(gen):
    _, root, txns = gen
    for d, rows in txns.items():
        manifest = json.loads((_folder(root, "payments", "transactions", d) / "_manifest.json").read_text())
        totals: dict[str, Decimal] = {}
        for r in rows:
            totals[r["currency"]] = totals.get(r["currency"], Decimal("0")) + Decimal(r["amount"])
        assert manifest["record_count"] == len(rows)
        assert manifest["amount_totals"] == {k: money(v) for k, v in sorted(totals.items())}


def test_fx_files_only_on_publication_days(gen):
    _, root, _ = gen
    for d in DAYS:
        folder = _folder(root, "reference", "fx_rates", d)
        assert folder.exists() == is_fx_publication_day(d)
        if folder.exists():
            rates = _load(folder)
            assert {r["currency"] for r in rates} == {"GBP", "PLN", "SEK", "USD"}
            assert all(Decimal(r["rate"]) > 0 for r in rates)
