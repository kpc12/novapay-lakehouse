"""Shared test helpers: read generated files the way a consumer would."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from data_generator.config import GenConfig

SIM_START, SIM_END = date(2026, 9, 1), date(2026, 11, 20)
DAYS = [SIM_START + timedelta(days=i) for i in range((SIM_END - SIM_START).days + 1)]


def small_cfg(root: Path) -> GenConfig:
    return replace(GenConfig(), output_root=root, n_customers=300, n_merchants=50)


def folder(root: Path, source: str, entity: str, d: date) -> Path:
    return root / source / entity / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}"


def load(path: Path) -> list[dict]:
    text = (path / "part-0001.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def load_all(root: Path, source: str, entity: str) -> list[tuple[date, dict]]:
    rows: list[tuple[date, dict]] = []
    for d in DAYS:
        f = folder(root, source, entity, d)
        if f.exists():
            rows += [(d, r) for r in load(f)]
    return rows


def alias_map(root: Path) -> dict[str, str]:
    return {r["old_customer_id"]: r["customer_id"]
            for _, r in load_all(root, "core_banking", "customers") if r.get("old_customer_id")}
