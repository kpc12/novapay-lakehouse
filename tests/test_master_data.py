"""Tests for day-0 master data. Run from the repo root: python -m pytest"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from data_generator.common import SCHEMA_VERSION
from data_generator.config import GenConfig
from data_generator.master_data import PHONE_PREFIX, generate_initial

START = GenConfig().start_date
KEYS = {"customers": ("customer_id",), "accounts": ("account_id",),
        "account_holders": ("account_id", "customer_id"), "merchants": ("merchant_id",),
        "billers": ("biller_id",), "invest_products": ("isin",)}


def _generate(root: Path) -> dict[str, Path]:
    cfg = replace(GenConfig(), output_root=root, n_customers=300, n_merchants=50)
    return {folder.parts[-4]: folder for folder in generate_initial(cfg)}  # key = entity name


def _load(folder: Path) -> list[dict]:
    lines = (folder / "part-0001.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> dict[str, Path]:
    return _generate(tmp_path_factory.mktemp("gen"))


def test_deterministic(tmp_path):
    a, b = _generate(tmp_path / "a"), _generate(tmp_path / "b")
    for entity in a:
        assert (a[entity] / "part-0001.jsonl").read_bytes() == (b[entity] / "part-0001.jsonl").read_bytes()


def test_manifest_matches_data(out):
    for folder in out.values():
        manifest = json.loads((folder / "_manifest.json").read_text(encoding="utf-8"))
        data = (folder / "part-0001.jsonl").read_bytes()
        assert manifest["schema_version"] == SCHEMA_VERSION
        assert manifest["record_count"] == len(data.splitlines()) == manifest["files"][0]["records"]
        assert manifest["files"][0]["sha256"] == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("entity,key", KEYS.items())
def test_business_keys_unique(out, entity, key):
    keys = [tuple(r[k] for k in key) for r in _load(out[entity])]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("entity", ["customers", "accounts", "account_holders", "merchants"])
def test_change_seq_increasing_and_dated(out, entity):
    seqs = [r["change_seq"] for r in _load(out[entity])]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert all(str(s).startswith(START.strftime("%Y%m%d")) for s in seqs)


def test_credit_cards_and_joint_holders_only_verified(out):
    customers = {c["customer_id"]: c for c in _load(out["customers"])}
    cards = {a["account_id"] for a in _load(out["accounts"]) if a["account_type"] == "credit_card"}
    for h in _load(out["account_holders"]):
        if h["role"] == "joint" or h["account_id"] in cards:
            assert customers[h["customer_id"]]["kyc_status"] == "verified"


def test_joint_holder_differs_from_primary(out):
    holders = _load(out["account_holders"])
    primary = {h["account_id"]: h["customer_id"] for h in holders if h["role"] == "primary"}
    for h in holders:
        if h["role"] == "joint":
            assert h["customer_id"] != primary[h["account_id"]]


def test_open_date_window(out):
    customers = {c["customer_id"]: c for c in _load(out["customers"])}
    primary = {h["account_id"]: h["customer_id"] for h in _load(out["account_holders"]) if h["role"] == "primary"}
    for a in _load(out["accounts"]):
        since = date.fromisoformat(customers[primary[a["account_id"]]]["customer_since"])
        assert since <= date.fromisoformat(a["open_date"]) < START


def test_phone_prefix_matches_country(out):
    for c in _load(out["customers"]):
        assert c["phone"].startswith(PHONE_PREFIX[c["country"]])


def test_rerun_clears_partition(tmp_path):
    folder = _generate(tmp_path)["customers"]
    (folder / "part-0002.jsonl").write_text("stale\n", encoding="utf-8")
    _generate(tmp_path)
    assert sorted(p.name for p in folder.iterdir()) == ["_manifest.json", "part-0001.jsonl"]
