"""Tests for delivery to the landing volume (Step 1.6), using a local stand-in for the volume."""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import date

import pytest

from data_generator.chaos import apply_chaos
from data_generator.upload import (LANDING_VOLUME, MANIFEST, LocalTarget, UploadError, deliver_late,
                                   find_batches, redeliver, upload)

START, END = date(2026, 9, 19), date(2026, 9, 23)


@pytest.fixture()
def env(sim, tmp_path):
    cfg, clean = sim
    out = tmp_path / "out"
    shutil.copytree(clean, out)
    apply_chaos(replace(cfg, output_root=out))
    return out, LocalTarget(tmp_path / "volume")


def test_first_week_has_72_batches(sim):
    assert len(find_batches(sim[1], date(2026, 9, 1), date(2026, 9, 7))) == 72


def test_upload_orders_manifest_last_and_skips_control_folders(env):
    out, target = env
    result = upload(target, out, LANDING_VOLUME, START, END)
    assert result.files == len(target.calls) > 0
    assert not any(seg in c for c in target.calls for seg in ("/_chaos", "/_late", "/_uploads"))
    position = {c: i for i, c in enumerate(target.calls)}
    for c in target.calls:
        if c.endswith(MANIFEST):
            folder = c.rsplit("/", 1)[0]
            assert all(position[x] < position[c] for x in target.calls if x.startswith(folder + "/") and x != c)
    dates = [c.split("/")[-4:-1] for c in target.calls]
    assert dates == sorted(dates)
    assert f"{LANDING_VOLUME}/payments/transactions/2026/09/20/{MANIFEST}" not in position
    assert target.list_files(f"{LANDING_VOLUME}/payments/transactions/2026/09/21") == {
        "part-0001.jsonl", "part-0002.jsonl", MANIFEST}


def test_rerun_is_idempotent(env):
    out, target = env
    upload(target, out, LANDING_VOLUME, START, END)
    n = len(target.calls)
    again = upload(target, out, LANDING_VOLUME, START, END)
    assert again.files == 0 and again.batches == 0 and len(target.calls) == n


def test_changed_data_is_never_overwritten(env):
    out, target = env
    upload(target, out, LANDING_VOLUME, START, START)
    data = out / "payments/transactions/2026/09/19/part-0001.jsonl"
    data.write_text(data.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(UploadError):
        upload(target, out, LANDING_VOLUME, START, START)


def test_unknown_landing_content_is_refused(env):
    out, target = env
    upload(target, out, LANDING_VOLUME, START, START)
    (out / "_uploads" / "ledger.jsonl").unlink()
    with pytest.raises(UploadError):
        upload(target, out, LANDING_VOLUME, START, START)


def test_late_delivery_lands_in_the_normal_path(env):
    out, target = env
    upload(target, out, LANDING_VOLUME, START, END)
    result = deliver_late(target, out, LANDING_VOLUME)
    late_dir = f"{LANDING_VOLUME}/payments/transactions/2026/09/20"
    assert result.batches == 1
    assert target.calls[-1] == f"{late_dir}/{MANIFEST}"
    assert target.list_files(late_dir) == {"part-0001.jsonl", MANIFEST}


def test_redelivery_adds_a_new_part_and_superseding_manifest(env):
    out, target = env
    upload(target, out, LANDING_VOLUME, START, END)
    remote = f"{LANDING_VOLUME}/payments/transactions/2026/09/22"
    folder = target.root / remote.lstrip("/")
    truncated = (folder / "part-0001.jsonl").read_bytes()
    result = redeliver(target, out, LANDING_VOLUME)
    assert result.batches == 1 and result.files == 2
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    part2 = (folder / "part-0002.jsonl").read_bytes()
    assert manifest["files"] == [{"name": "part-0002.jsonl", "records": len(part2.splitlines()),
                                  "sha256": hashlib.sha256(part2).hexdigest()}]
    assert manifest["record_count"] == len(part2.splitlines())
    assert manifest["delivery_attempt"] == 2 and manifest["supersedes"] == ["part-0001.jsonl"]
    assert (folder / "part-0001.jsonl").read_bytes() == truncated      # never overwritten
    assert target.calls[-1] == f"{remote}/{MANIFEST}"
    assert redeliver(target, out, LANDING_VOLUME).files == 0           # idempotent
    assert upload(target, out, LANDING_VOLUME, START, END).files == 0  # superseded batch left alone


def test_redelivery_requires_the_original_first(env):
    out, target = env
    with pytest.raises(UploadError):
        redeliver(target, out, LANDING_VOLUME)
