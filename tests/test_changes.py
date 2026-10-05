"""Tests for daily master-data change records (Step 1.4a). Run: python -m pytest"""
from __future__ import annotations

from helpers import DAYS, folder, load, load_all

from data_generator.state import (BILLER_ADDED, BILLER_REMOVED, KEY_CHANGE_COUNT, KEY_CHANGE_DATE,
                                  PRODUCT_CHANGE)

CHANGE_ENTITIES = [("core_banking", "customers"), ("core_banking", "accounts"),
                   ("core_banking", "account_holders"), ("acquirer", "merchants")]


def test_change_files_delivered_every_day(sim):
    for d in DAYS[1:]:
        for source, entity in CHANGE_ENTITIES:
            f = folder(sim[1], source, entity, d)
            assert (f / "part-0001.jsonl").exists() and (f / "_manifest.json").exists()


def test_change_seq_increasing_across_days(sim):
    for source, entity in CHANGE_ENTITIES:
        seqs = [r["change_seq"] for _, r in load_all(sim[1], source, entity)]
        assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))


def test_key_change(sim):
    root = sim[1]
    changed = [r for r in load(folder(root, "core_banking", "customers", KEY_CHANGE_DATE)) if r["old_customer_id"]]
    assert len(changed) == KEY_CHANGE_COUNT
    old_ids = {r["old_customer_id"] for r in changed}
    holders = load(folder(root, "core_banking", "account_holders", KEY_CHANGE_DATE))
    for r in changed:
        deleted = {h["account_id"] for h in holders if h["op"] == "D" and h["customer_id"] == r["old_customer_id"]}
        inserted = {h["account_id"] for h in holders if h["op"] == "I" and h["customer_id"] == r["customer_id"]}
        assert deleted and deleted == inserted
    for d in DAYS:
        if d >= KEY_CHANGE_DATE:
            assert not [t for t in load(folder(root, "payments", "transactions", d)) if t["customer_id"] in old_ids]
        if d > KEY_CHANGE_DATE:
            assert not [c for c in load(folder(root, "core_banking", "customers", d)) if c["customer_id"] in old_ids]


def test_holder_deletes_reference_existing_rows(sim):
    live: set[tuple[str, str]] = set()
    for _, r in load_all(sim[1], "core_banking", "account_holders"):
        key = (r["account_id"], r["customer_id"])
        if r["op"] == "I":
            live.add(key)
        elif r["op"] == "D":
            assert key in live
            live.remove(key)


def test_closed_accounts_stop_transacting(sim):
    closed = {}
    for d, r in load_all(sim[1], "core_banking", "accounts"):
        if r["op"] == "U" and r["status"] == "closed":
            closed.setdefault(r["account_id"], d)
    for d in DAYS:
        for t in load(folder(sim[1], "payments", "transactions", d)):
            if t["account_id"] in closed:
                assert d < closed[t["account_id"]]


def test_new_customers_get_current_account_same_day(sim):
    root = sim[1]
    for d in DAYS[1:]:
        new = {r["customer_id"] for r in load(folder(root, "core_banking", "customers", d)) if r["op"] == "I"}
        if not new:
            continue
        accounts = {r["account_id"]: r for r in load(folder(root, "core_banking", "accounts", d)) if r["op"] == "I"}
        primaries = {h["customer_id"] for h in load(folder(root, "core_banking", "account_holders", d))
                     if h["op"] == "I" and h["role"] == "primary"
                     and accounts.get(h["account_id"], {}).get("account_type") == "current"}
        assert new <= primaries


def test_reference_snapshots_follow_scenario(sim):
    isin, new_risk, change_day = PRODUCT_CHANGE
    for d in DAYS[1:]:
        billers = {b["biller_id"] for b in load(folder(sim[1], "reference", "billers", d))}
        assert (BILLER_ADDED[0] in billers) == (d >= BILLER_ADDED[3])
        assert (BILLER_REMOVED[0] in billers) == (d < BILLER_REMOVED[1])
        risk = {p["isin"]: p["risk_level"] for p in load(folder(sim[1], "reference", "invest_products", d))}
        assert (risk[isin] == new_risk) == (d >= change_day)


def test_bill_payments_respect_biller_lifecycle(sim):
    for d in DAYS:
        for t in load(folder(sim[1], "payments", "transactions", d)):
            if t["transaction_type"] != "bill_payment":
                continue
            if t["biller_id"] == BILLER_ADDED[0]:
                assert d >= BILLER_ADDED[3]
            if t["biller_id"] == BILLER_REMOVED[0]:
                assert d < BILLER_REMOVED[1]
