"""Tests for chaos injection part A (Step 1.5a). Run from the repo root: python -m pytest"""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import pytest
from helpers import alias_map, folder

from data_generator.chaos import SCENARIO_CODES, ChaosError, apply_chaos
from data_generator.state import KEY_CHANGE_DATE

TXN = ("payments", "transactions")


def _lines(root, source, entity, d):
    return (folder(root, source, entity, d) / "part-0001.jsonl").read_text(encoding="utf-8").splitlines()


def _parsed(lines):
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


@pytest.fixture(scope="module")
def chaos(sim, tmp_path_factory):
    cfg, clean = sim
    root = tmp_path_factory.mktemp("chaos") / "out"
    shutil.copytree(clean, root)
    cfg2 = replace(cfg, output_root=root)
    log = {e["code"]: e for e in apply_chaos(cfg2)}
    return cfg2, root, clean, log


def _entry_lines(chaos, code):
    _, root, _, log = chaos
    e = log[code]
    return e, _lines(root, e["source"], e["entity"], date.fromisoformat(e["business_date"]))


def test_every_scenario_applied_and_logged(chaos):
    _, root, _, log = chaos
    assert list(log) == SCENARIO_CODES
    assert all(e["affected"] > 0 for e in log.values())
    assert (root / "_chaos" / "applied.json").exists()


def test_manifests_still_describe_their_files(chaos):
    _, root, _, log = chaos
    targets = {(e["source"], e["entity"], e["business_date"]) for e in log.values()}
    targets.add(("acquirer", "merchants", log["S06_LATE_ARRIVING_DIMENSION"]["dimension_arrives"]))
    for source, entity, day in targets:
        f = folder(root, source, entity, date.fromisoformat(day))
        data = (f / "part-0001.jsonl").read_bytes()
        manifest = json.loads((f / "_manifest.json").read_text(encoding="utf-8"))
        assert manifest["record_count"] == len(data.splitlines())
        assert manifest["files"][0]["sha256"] == hashlib.sha256(data).hexdigest()


def test_s01_malformed_lines(chaos):
    e, lines = _entry_lines(chaos, "S01_MALFORMED_JSON")
    bad = 0
    for line in lines:
        try:
            json.loads(line)
        except json.JSONDecodeError:
            bad += 1
    assert bad == e["affected"] == 3


def test_s02_type_mismatches(chaos):
    e, lines = _entry_lines(chaos, "S02_TYPE_MISMATCH")
    by_id = {r["transaction_id"]: r for r in _parsed(lines)}
    for tid in e["ids"]:
        r = by_id[tid]
        try:
            Decimal(r["amount"])
            amount_ok = True
        except InvalidOperation:
            amount_ok = False
        try:
            datetime.strptime(r["event_ts"], "%Y-%m-%dT%H:%M:%SZ")
            ts_ok = True
        except ValueError:
            ts_ok = False
        assert not (amount_ok and ts_ok)


def test_s03_missing_keys(chaos):
    e, lines = _entry_lines(chaos, "S03_MISSING_BUSINESS_KEY")
    assert sum(r["transaction_id"] is None for r in _parsed(lines)) == e["affected"] == 2


def test_s04_invalid_values(chaos):
    e, lines = _entry_lines(chaos, "S04_INVALID_VALUES")
    by_id = {r["transaction_id"]: r for r in _parsed(lines)}
    issue = {x["issue"]: by_id[x["transaction_id"]] for x in e["issues"]}
    assert issue["invalid_currency"]["currency"] == "EUX"
    assert Decimal(issue["negative_amount"]["amount"]) < 0
    assert issue["future_event_ts"]["event_ts"].startswith("2027-")
    assert issue["bill_without_biller"]["biller_id"] is None


def test_s05_duplicates(chaos):
    e, lines = _entry_lines(chaos, "S05_DUPLICATES_IN_FILE")
    _, _, clean, _ = chaos
    assert len(lines) == len(_lines(clean, *TXN, date.fromisoformat(e["business_date"]))) + 10
    counts = Counter(r["transaction_id"] for r in _parsed(lines))
    assert sorted(t for t, n in counts.items() if n == 2) == sorted(e["ids"])


def test_s06_late_arriving_dimension(chaos):
    _, root, _, log = chaos
    e = log["S06_LATE_ARRIVING_DIMENSION"]
    mid = e["merchant_id"]
    txn_day, dim_day = date.fromisoformat(e["business_date"]), date.fromisoformat(e["dimension_arrives"])
    assert sum(r["merchant_id"] == mid for r in _parsed(_lines(root, *TXN, txn_day))) == 3
    first_seen, d = None, date(2026, 9, 1)
    while d <= dim_day:
        if first_seen is None and any(r["merchant_id"] == mid
                                      for r in _parsed(_lines(root, "acquirer", "merchants", d))):
            first_seen = d
        d += timedelta(days=1)
    assert first_seen == dim_day
    seqs = [r["change_seq"] for r in _parsed(_lines(root, "acquirer", "merchants", dim_day))]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))


def test_s07_late_fact_with_old_customer_id(chaos):
    _, root, _, log = chaos
    e = log["S07_LATE_FACT_OLD_KEY"]
    d = date.fromisoformat(e["business_date"])
    rows = {r["transaction_id"]: r for r in _parsed(_lines(root, *TXN, d))}
    assert d > KEY_CHANGE_DATE
    assert rows[e["ids"][0]]["customer_id"] in set(alias_map(root))


def test_untouched_files_identical(chaos):
    _, root, clean, _ = chaos
    for d in (date(2026, 9, 12), date(2026, 9, 13)):
        rel = folder(root, *TXN, d).relative_to(root) / "part-0001.jsonl"
        assert (root / rel).read_bytes() == (clean / rel).read_bytes()


def test_reapply_is_refused(chaos):
    with pytest.raises(ChaosError):
        apply_chaos(chaos[0])


def test_refuses_without_data_and_changes_nothing(sim, tmp_path):
    cfg = replace(sim[0], output_root=tmp_path / "empty")
    with pytest.raises(ChaosError):
        apply_chaos(cfg)
    assert not (tmp_path / "empty" / "_chaos").exists()
