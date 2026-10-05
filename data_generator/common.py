"""Shared helpers for the NovaPay synthetic data generator."""
from __future__ import annotations

import hashlib
import json
import random
import shutil
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "1.0"      # contract version carried in every manifest
CENT = Decimal("0.01")
SEQ_DAY_FACTOR = 10_000_000  # up to 9,999,999 changes per entity per day


def rng_for(seed: int, *parts: object) -> random.Random:
    """Deterministic RNG per (seed, parts): same inputs always give the same data."""
    return random.Random("|".join([str(seed), *map(str, parts)]))


def money(value: Decimal | float | int | str) -> str:
    """Money as a string with exactly 2 decimals (avoids float rounding errors)."""
    return str(Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP))


def utc_ts(dt: datetime) -> str:
    """ISO-8601 UTC timestamp, e.g. 2026-09-15T10:42:11Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def change_seq(business_date: date, n: int) -> int:
    """Ordering key that keeps increasing across days, e.g. 202609010000001."""
    if not 1 <= n < SEQ_DAY_FACTOR:
        raise ValueError(f"change sequence {n} out of range for one day")
    return int(business_date.strftime("%Y%m%d")) * SEQ_DAY_FACTOR + n


def change_time(business_date: date, seconds: int) -> str:
    """Timestamp for change records: 01:00 UTC on the business date + offset."""
    base = datetime.combine(business_date, time(1, 0), tzinfo=timezone.utc)
    return utc_ts(base + timedelta(seconds=seconds))


def ascii_slug(text: str) -> str:
    """'Žydrūnas' -> 'zydrunas' (used to build e-mail addresses)."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def partition_dir(root: Path, source: str, entity: str, business_date: date) -> Path:
    return root / source / entity / f"{business_date:%Y}" / f"{business_date:%m}" / f"{business_date:%d}"


def _amount_totals(records: Iterable[dict], amount_field: str | None,
                   currency_field: str | None) -> dict[str, str] | None:
    """Control totals per currency (mixed-currency sums are meaningless)."""
    if amount_field is None:
        return None
    totals: dict[str, Decimal] = {}
    for r in records:
        try:
            amount = Decimal(str(r.get(amount_field)))
        except (InvalidOperation, TypeError):
            continue  # unparseable amounts are not counted
        key = str(r.get(currency_field)) if currency_field else "ALL"
        totals[key] = totals.get(key, Decimal("0")) + amount
    return {k: money(v) for k, v in sorted(totals.items())}


def write_batch(root: Path, source: str, entity: str, business_date: date, records: list[dict],
                amount_field: str | None = None, currency_field: str | None = None) -> Path:
    """Replace the partition, write JSON Lines, then the manifest LAST."""
    out_dir = partition_dir(root, source, entity, business_date)
    if out_dir.exists():
        shutil.rmtree(out_dir)  # a rerun produces exactly one clean batch
    out_dir.mkdir(parents=True)
    data_file = out_dir / "part-0001.jsonl"
    with data_file.open("w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    generated = datetime.combine(business_date + timedelta(days=1), time(0, 30), tzinfo=timezone.utc)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "entity": entity,
        "business_date": business_date.isoformat(),
        "files": [{
            "name": data_file.name,
            "records": len(records),
            "sha256": hashlib.sha256(data_file.read_bytes()).hexdigest(),
        }],
        "record_count": len(records),
        "amount_field": amount_field,
        "currency_field": currency_field,
        "amount_totals": _amount_totals(records, amount_field, currency_field),
        "generated_at": utc_ts(generated),
    }
    (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out_dir
