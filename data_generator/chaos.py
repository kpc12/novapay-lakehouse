"""Chaos injection, part A: record-level production faults (Step 1.5a).

Clean generator output stays the reference. Chaos is applied afterwards, exactly once,
and every change is logged in <output>/_chaos/applied.json so later phases can prove
they catch each fault. To apply again: delete the output folder, run init and daily, then chaos."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from random import Random

from .common import _amount_totals, change_seq, change_time, partition_dir, rng_for
from .config import GenConfig
from .state import KEY_CHANGE_DATE

CHAOS_DIR = "_chaos"
TXN = ("payments", "transactions")
MERCHANTS = ("acquirer", "merchants")
CUSTOMERS = ("core_banking", "customers")
LATE_MERCHANT_ID = "M-90001"
SCENARIO_CODES = ["S01_MALFORMED_JSON", "S02_TYPE_MISMATCH", "S03_MISSING_BUSINESS_KEY",
                  "S04_INVALID_VALUES", "S05_DUPLICATES_IN_FILE", "S06_LATE_ARRIVING_DIMENSION",
                  "S07_LATE_FACT_OLD_KEY"]
# Every file a scenario needs; checked BEFORE anything is modified.
REQUIRED = [(TXN, date(2026, 9, 8)), (TXN, date(2026, 9, 9)), (TXN, date(2026, 9, 10)),
            (TXN, date(2026, 9, 11)), (TXN, date(2026, 9, 14)), (TXN, date(2026, 9, 16)),
            (MERCHANTS, date(2026, 9, 18)), (CUSTOMERS, KEY_CHANGE_DATE),
            (TXN, KEY_CHANGE_DATE + timedelta(days=1))]


class ChaosError(RuntimeError):
    """Chaos cannot be applied safely (missing data or already applied)."""


def _dump(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


@dataclass
class Batch:
    """One delivered batch (data file + manifest) that a scenario edits line by line."""
    folder: Path
    lines: list[str]

    @classmethod
    def load(cls, root: Path, target: tuple[str, str], d: date) -> "Batch":
        folder = partition_dir(root, target[0], target[1], d)
        data = folder / "part-0001.jsonl"
        if not data.exists():
            raise ChaosError(f"missing {data}")
        return cls(folder, data.read_text(encoding="utf-8").splitlines())

    def records(self) -> list[tuple[int, dict]]:
        """(line index, record) for every line that is valid JSON."""
        out = []
        for i, line in enumerate(self.lines):
            try:
                out.append((i, json.loads(line)))
            except json.JSONDecodeError:
                continue
        return out

    def save(self) -> None:
        """Rewrite the data file and refresh its manifest (the SOURCE sent this content,
        so the manifest describes it: counts every line, totals only parseable amounts)."""
        data = self.folder / "part-0001.jsonl"
        with data.open("w", encoding="utf-8", newline="\n") as f:
            f.writelines(line + "\n" for line in self.lines)
        manifest_path = self.folder / "_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"] = [{"name": data.name, "records": len(self.lines),
                              "sha256": hashlib.sha256(data.read_bytes()).hexdigest()}]
        manifest["record_count"] = len(self.lines)
        manifest["amount_totals"] = _amount_totals([r for _, r in self.records()],
                                                   manifest["amount_field"], manifest["currency_field"])
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _entry(code: str, target: tuple[str, str], d: date, ids: list, **extra: object) -> dict:
    return {"code": code, "source": target[0], "entity": target[1], "business_date": d.isoformat(),
            "affected": len(ids), "ids": ids, **extra}


def _pick(rng: Random, candidates: list, k: int, what: str) -> list:
    if len(candidates) < k:
        raise ChaosError(f"need {k} {what}, found {len(candidates)}")
    return rng.sample(candidates, k)


def s01_malformed_json(cfg: GenConfig, root: Path) -> dict:
    """3 lines cut mid-record (e.g. a writer crashed): not valid JSON."""
    d = date(2026, 9, 8)
    batch = Batch.load(root, TXN, d)
    chosen = _pick(rng_for(cfg.seed, "chaos", "S01"), batch.records(), 3, "records")
    for i, _ in chosen:
        batch.lines[i] = batch.lines[i][: len(batch.lines[i]) // 2]
    batch.save()
    return _entry(SCENARIO_CODES[0], TXN, d, [r["transaction_id"] for _, r in chosen])


def s02_type_mismatch(cfg: GenConfig, root: Path) -> dict:
    """Decimal comma ('12,50'), non-numeric amount ('n/a') and a non-ISO timestamp."""
    d = date(2026, 9, 9)
    batch = Batch.load(root, TXN, d)
    purchases = [(i, r) for i, r in batch.records() if r["transaction_type"] == "purchase"]
    chosen = _pick(rng_for(cfg.seed, "chaos", "S02"), purchases, 4, "purchases")
    issues = []
    for n, (i, rec) in enumerate(chosen):
        if n < 2:
            rec["amount"], issue = rec["amount"].replace(".", ","), "decimal_comma"
        elif n == 2:
            rec["amount"], issue = "n/a", "non_numeric_amount"
        else:
            ts = datetime.strptime(rec["event_ts"], "%Y-%m-%dT%H:%M:%SZ")
            rec["event_ts"], issue = ts.strftime("%d/%m/%Y %H:%M"), "non_iso_timestamp"
        batch.lines[i] = _dump(rec)
        issues.append({"transaction_id": rec["transaction_id"], "issue": issue})
    batch.save()
    return _entry(SCENARIO_CODES[1], TXN, d, [x["transaction_id"] for x in issues], issues=issues)


def s03_missing_business_key(cfg: GenConfig, root: Path) -> dict:
    """2 records with transaction_id = null (the key Silver deduplicates and MERGEs on)."""
    d = date(2026, 9, 10)
    batch = Batch.load(root, TXN, d)
    chosen = _pick(rng_for(cfg.seed, "chaos", "S03"), batch.records(), 2, "records")
    ids = []
    for i, rec in chosen:
        ids.append(rec["transaction_id"])
        rec["transaction_id"] = None
        batch.lines[i] = _dump(rec)
    batch.save()
    return _entry(SCENARIO_CODES[2], TXN, d, ids, lines=[i + 1 for i, _ in chosen])


def s04_invalid_values(cfg: GenConfig, root: Path) -> dict:
    """Valid JSON and types, but values break contract rules."""
    d = date(2026, 9, 11)
    batch = Batch.load(root, TXN, d)
    records = batch.records()
    rng = rng_for(cfg.seed, "chaos", "S04")
    purchases = _pick(rng, [(i, r) for i, r in records if r["transaction_type"] == "purchase"], 3, "purchases")
    bills = _pick(rng, [(i, r) for i, r in records if r["transaction_type"] == "bill_payment"], 1, "bill payments")
    issues = []
    for (i, rec), issue in zip(purchases + bills,
                               ["invalid_currency", "negative_amount", "future_event_ts", "bill_without_biller"]):
        if issue == "invalid_currency":
            rec["currency"] = "EUX"
        elif issue == "negative_amount":
            rec["amount"] = "-" + rec["amount"]
        elif issue == "future_event_ts":
            rec["event_ts"] = "2027-01-01T00:00:00Z"
        else:
            rec["biller_id"] = None
        batch.lines[i] = _dump(rec)
        issues.append({"transaction_id": rec["transaction_id"], "issue": issue})
    batch.save()
    return _entry(SCENARIO_CODES[3], TXN, d, [x["transaction_id"] for x in issues], issues=issues)


def s05_duplicates_in_file(cfg: GenConfig, root: Path) -> dict:
    """10 records sent twice in the same file (source retry bug)."""
    d = date(2026, 9, 14)
    batch = Batch.load(root, TXN, d)
    chosen = _pick(rng_for(cfg.seed, "chaos", "S05"), batch.records(), 10, "records")
    for i in sorted((i for i, _ in chosen), reverse=True):
        batch.lines.insert(i + 1, batch.lines[i])
    batch.save()
    return _entry(SCENARIO_CODES[4], TXN, d, [r["transaction_id"] for _, r in chosen])


def s06_late_arriving_dimension(cfg: GenConfig, root: Path) -> dict:
    """3 purchases on 16 Sep reference merchant M-90001, whose master record arrives on 18 Sep."""
    d_txn, d_dim = date(2026, 9, 16), date(2026, 9, 18)
    referenced: set[str] = set()   # purchases later refunded keep their merchant (refund consistency)
    for k in range(1, 11):
        later = partition_dir(root, TXN[0], TXN[1], d_txn + timedelta(days=k)) / "part-0001.jsonl"
        if later.exists():
            for line in later.read_text(encoding="utf-8").splitlines():
                try:
                    ref = json.loads(line).get("original_transaction_id")
                except json.JSONDecodeError:
                    continue
                if ref:
                    referenced.add(ref)
    batch = Batch.load(root, TXN, d_txn)
    candidates = [(i, r) for i, r in batch.records() if r["transaction_type"] == "purchase"
                  and r["currency"] == "EUR" and r["transaction_id"] not in referenced]
    chosen = _pick(rng_for(cfg.seed, "chaos", "S06"), candidates, 3, "EUR purchases")
    for i, rec in chosen:
        rec["merchant_id"] = LATE_MERCHANT_ID
        batch.lines[i] = _dump(rec)
    batch.save()
    merchants = Batch.load(root, MERCHANTS, d_dim)
    n = len(merchants.lines) + 1
    merchants.lines.append(_dump({"op": "I", "change_seq": change_seq(d_dim, n), "change_ts": change_time(d_dim, n),
                                  "merchant_id": LATE_MERCHANT_ID, "merchant_name": "Amber Groceries 90001",
                                  "mcc": "5411", "category": "Groceries", "city": "Vilnius", "country": "LT"}))
    merchants.save()
    return _entry(SCENARIO_CODES[5], TXN, d_txn, [r["transaction_id"] for _, r in chosen],
                  merchant_id=LATE_MERCHANT_ID, dimension_arrives=d_dim.isoformat())


def s07_late_fact_old_key(cfg: GenConfig, root: Path) -> dict:
    """After the 15 Oct key change, one transaction still arrives with the OLD customer id."""
    customers = Batch.load(root, CUSTOMERS, KEY_CHANGE_DATE)
    new_to_old = {r["customer_id"]: r["old_customer_id"] for _, r in customers.records() if r.get("old_customer_id")}
    if not new_to_old:
        raise ChaosError(f"no key change found on {KEY_CHANGE_DATE}")
    rng = rng_for(cfg.seed, "chaos", "S07")
    for offset in range(1, 8):
        d = KEY_CHANGE_DATE + timedelta(days=offset)
        batch = Batch.load(root, TXN, d)
        candidates = [(i, r) for i, r in batch.records()
                      if r["customer_id"] in new_to_old and r["transaction_type"] != "refund"]
        if candidates:
            i, rec = rng.choice(candidates)
            new_id = rec["customer_id"]
            rec["customer_id"] = new_to_old[new_id]
            batch.lines[i] = _dump(rec)
            batch.save()
            return _entry(SCENARIO_CODES[6], TXN, d, [rec["transaction_id"]],
                          old_customer_id=rec["customer_id"], current_customer_id=new_id)
    raise ChaosError("no transaction of a re-keyed customer within 7 days of the key change")


SCENARIOS = [s01_malformed_json, s02_type_mismatch, s03_missing_business_key, s04_invalid_values,
             s05_duplicates_in_file, s06_late_arriving_dimension, s07_late_fact_old_key]


def apply_chaos(cfg: GenConfig) -> list[dict]:
    """Apply every scenario once and write the log. Refuses if already applied or data is missing."""
    root = cfg.output_root
    chaos_dir = root / CHAOS_DIR
    if chaos_dir.exists():
        raise ChaosError(f"{chaos_dir} exists: chaos already applied (or interrupted). "
                         "Regenerate clean data: delete the output folder, then run init and daily.")
    for (source, entity), d in REQUIRED:
        if not (partition_dir(root, source, entity, d) / "part-0001.jsonl").exists():
            raise ChaosError(f"missing {source}/{entity} for {d}: run init and daily through at least 2026-10-22")
    chaos_dir.mkdir(parents=True)
    log = [scenario(cfg, root) for scenario in SCENARIOS]
    (chaos_dir / "applied.json").write_text(json.dumps({"scenarios": log}, indent=2) + "\n", encoding="utf-8")
    return log
