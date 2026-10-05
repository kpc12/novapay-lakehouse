"""Tests for chaos injection (Steps 1.5a-1.5b). Run from the repo root: python -m pytest"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import pytest
from helpers import alias_map, folder

from data_generator.chaos import SCENARIO_CODES, ChaosError, apply_chaos
from data_generator.state import KEY_CHANGE_DATE

TXN = ("payments", "transactions")
VILNIUS = ZoneInfo("Europe/Vilnius")
UTC_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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


def _manifest(f):
    return json.loads((f / "_manifest.json").read_text(encoding="utf-8"))


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


# ---------------------------------------------------------------- framework
def test_every_scenario_applied_and_logged(chaos):
    _, root, _, log = chaos
    assert list(log) == SCENARIO_CODES
    assert all(e["affected"] > 0 for e in log.values())
    assert (root / "_chaos" / "applied.json").exists()


def test_recomputed_manifests_describe_their_files(chaos):
    _, root, _, log = chaos
    for e in log.values():
        for t in e["touched"]:
            if t["manifest"] != "recomputed":
                continue
            f = folder(root, t["source"], t["entity"], date.fromisoformat(t["business_date"]))
            manifest = _manifest(f)
            total = 0
            for item in manifest["files"]:
                data = (f / item["name"]).read_bytes()
                assert item["sha256"] == hashlib.sha256(data).hexdigest()
                assert item["records"] == len(data.splitlines())
                total += item["records"]
            assert manifest["record_count"] == total


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


# ---------------------------------------------------------------- part A (1.5a)
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


# ---------------------------------------------------------------- part B (1.5b)
def test_s08_resent_file(chaos):
    _, root, _, log = chaos
    e = log["S08_RESENT_FILE"]
    f = folder(root, *TXN, date.fromisoformat(e["business_date"]))
    first, second = (f / "part-0001.jsonl").read_bytes(), (f / "part-0002.jsonl").read_bytes()
    assert first == second
    manifest = _manifest(f)
    assert [x["name"] for x in manifest["files"]] == ["part-0001.jsonl", "part-0002.jsonl"]
    assert manifest["files"][0]["sha256"] == manifest["files"][1]["sha256"]
    assert manifest["record_count"] == 2 * len(first.splitlines()) == 2 * e["affected"]


def test_s09_truncated_upload_with_stale_manifest(chaos):
    _, root, _, log = chaos
    e = log["S09_TRUNCATED_UPLOAD"]
    f = folder(root, *TXN, date.fromisoformat(e["business_date"]))
    data = (f / "part-0001.jsonl").read_bytes()
    lines = data.decode("utf-8").splitlines()
    manifest = _manifest(f)
    assert manifest["record_count"] == e["expected_records"] != len(lines)
    assert manifest["files"][0]["sha256"] != hashlib.sha256(data).hexdigest()
    with pytest.raises(json.JSONDecodeError):
        json.loads(lines[-1])
    original = (root / e["redelivery"] / "part-0001.jsonl").read_bytes()
    assert hashlib.sha256(original).hexdigest() == manifest["files"][0]["sha256"]


def test_s10_late_file_held_back(chaos):
    _, root, _, log = chaos
    e = log["S10_LATE_FILE"]
    assert not folder(root, *TXN, date.fromisoformat(e["business_date"])).exists()
    late = root / e["moved_to"]
    lines = (late / "part-0001.jsonl").read_text(encoding="utf-8").splitlines()
    assert _manifest(late)["record_count"] == len(lines) == e["affected"]


def test_s11_added_field_announced_as_1_1(chaos):
    _, root, _, log = chaos
    for t in log["S11_ADDED_FIELD"]["touched"]:
        d = date.fromisoformat(t["business_date"])
        assert _manifest(folder(root, *TXN, d))["schema_version"] == "1.1"
        assert all("device_type" in r for r in _parsed(_lines(root, *TXN, d)))
    before = date(2026, 9, 30)
    assert _manifest(folder(root, *TXN, before))["schema_version"] == "1.0"
    assert not any("device_type" in r for r in _parsed(_lines(root, *TXN, before)))


def test_s12_renamed_field_without_version_bump(chaos):
    _, root, _, log = chaos
    for t in log["S12_RENAMED_FIELD"]["touched"]:
        d = date.fromisoformat(t["business_date"])
        assert _manifest(folder(root, *TXN, d))["schema_version"] == "1.1"
        assert all("merchant_ref" in r and "merchant_id" not in r for r in _parsed(_lines(root, *TXN, d)))
    assert all("merchant_id" in r for r in _parsed(_lines(root, *TXN, date(2026, 11, 8))))


def test_s13_due_date_becomes_utc_timestamp_of_local_midnight(chaos):
    _, root, _, log = chaos
    for t in log["S13_DUE_DATE_FORMAT"]["touched"]:
        d = date.fromisoformat(t["business_date"])
        for r in _parsed(_lines(root, *TXN, d)):
            if r["transaction_type"] != "bill_payment":
                continue
            assert UTC_TS.match(r["due_date"])
            local = datetime.strptime(r["due_date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            local = local.astimezone(VILNIUS)
            assert (local.hour, local.minute) == (0, 0)
            assert -5 <= (d - local.date()).days <= 10
    for r in _parsed(_lines(root, *TXN, date(2026, 11, 1))):
        if r["transaction_type"] == "bill_payment":
            date.fromisoformat(r["due_date"])          # still plain yyyy-mm-dd before the change
