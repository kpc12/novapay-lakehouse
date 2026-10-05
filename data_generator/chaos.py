"""Chaos injection: deliberately break source files the way production does (Steps 1.5a-1.5b).

Clean generator output stays the reference. Chaos is applied afterwards, exactly once, and
every change is logged in <output>/_chaos/applied.json. Late files are held in <output>/_late/;
the intact original of the truncated upload is kept in <output>/_chaos/redelivery/.
To apply again: delete the output folder, run init and daily, then chaos."""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from random import Random
from typing import Iterator

from .common import _amount_totals, change_seq, change_time, partition_dir, rng_for, utc_ts
from .config import GenConfig
from .state import KEY_CHANGE_DATE
from .transactions import VILNIUS

CHAOS_DIR = "_chaos"
LATE_DIR = "_late"
TXN = ("payments", "transactions")
MERCHANTS = ("acquirer", "merchants")
CUSTOMERS = ("core_banking", "customers")
LATE_MERCHANT_ID = "M-90001"
DEVICE_BY_CHANNEL = {"pos": "pos_terminal", "online": "web_browser", "web": "web_browser",
                     "bank_network": "bank_system"}   # mobile_app -> ios / android
SCENARIO_CODES = ["S01_MALFORMED_JSON", "S02_TYPE_MISMATCH", "S03_MISSING_BUSINESS_KEY",
                  "S04_INVALID_VALUES", "S05_DUPLICATES_IN_FILE", "S06_LATE_ARRIVING_DIMENSION",
                  "S07_LATE_FACT_OLD_KEY", "S08_RESENT_FILE", "S09_TRUNCATED_UPLOAD", "S10_LATE_FILE",
                  "S11_ADDED_FIELD", "S12_RENAMED_FIELD", "S13_DUE_DATE_FORMAT"]
# Every file a scenario needs; all checked BEFORE anything is modified.
REQUIRED = [(TXN, date(2026, 9, 8)), (TXN, date(2026, 9, 9)), (TXN, date(2026, 9, 10)),
            (TXN, date(2026, 9, 11)), (TXN, date(2026, 9, 14)), (TXN, date(2026, 9, 16)),
            (MERCHANTS, date(2026, 9, 18)), (CUSTOMERS, KEY_CHANGE_DATE),
            (TXN, KEY_CHANGE_DATE + timedelta(days=1)), (TXN, date(2026, 9, 20)),
            (TXN, date(2026, 9, 21)), (TXN, date(2026, 9, 22)), (TXN, date(2026, 10, 1)),
            (TXN, date(2026, 11, 2)), (TXN, date(2026, 11, 9))]
Touched = tuple[tuple[str, str], date, str]   # (target, business date, manifest state)


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

    def save(self, schema_version: str | None = None) -> None:
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
        if schema_version is not None:
            manifest["schema_version"] = schema_version
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _entry(code: str, target: tuple[str, str], d: date, *, affected: int, touched: list[Touched],
           ids: list | None = None, **extra: object) -> dict:
    return {"code": code, "source": target[0], "entity": target[1], "business_date": d.isoformat(),
            "affected": affected, "ids": ids or [],
            "touched": [{"source": t[0], "entity": t[1], "business_date": x.isoformat(), "manifest": m}
                        for t, x, m in touched],
            **extra}


def _pick(rng: Random, candidates: list, k: int, what: str) -> list:
    if len(candidates) < k:
        raise ChaosError(f"need {k} {what}, found {len(candidates)}")
    return rng.sample(candidates, k)


def _existing_days(root: Path, target: tuple[str, str], start: date) -> Iterator[date]:
    """Consecutive business dates from start for which the batch exists."""
    d = start
    while (partition_dir(root, target[0], target[1], d) / "part-0001.jsonl").exists():
        yield d
        d += timedelta(days=1)


# ------------------------------------------------ Part A: record-level faults (1.5a)
def s01_malformed_json(cfg: GenConfig, root: Path) -> dict:
    """3 lines cut mid-record (e.g. a writer crashed): not valid JSON."""
    d = date(2026, 9, 8)
    batch = Batch.load(root, TXN, d)
    chosen = _pick(rng_for(cfg.seed, "chaos", "S01"), batch.records(), 3, "records")
    for i, _ in chosen:
        batch.lines[i] = batch.lines[i][: len(batch.lines[i]) // 2]
    batch.save()
    return _entry(SCENARIO_CODES[0], TXN, d, affected=len(chosen),
                  ids=[r["transaction_id"] for _, r in chosen], touched=[(TXN, d, "recomputed")])


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
    return _entry(SCENARIO_CODES[1], TXN, d, affected=len(issues),
                  ids=[x["transaction_id"] for x in issues], touched=[(TXN, d, "recomputed")], issues=issues)


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
    return _entry(SCENARIO_CODES[2], TXN, d, affected=len(ids), ids=ids,
                  touched=[(TXN, d, "recomputed")], lines=[i + 1 for i, _ in chosen])


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
    return _entry(SCENARIO_CODES[3], TXN, d, affected=len(issues),
                  ids=[x["transaction_id"] for x in issues], touched=[(TXN, d, "recomputed")], issues=issues)


def s05_duplicates_in_file(cfg: GenConfig, root: Path) -> dict:
    """10 records sent twice in the same file (source retry bug)."""
    d = date(2026, 9, 14)
    batch = Batch.load(root, TXN, d)
    chosen = _pick(rng_for(cfg.seed, "chaos", "S05"), batch.records(), 10, "records")
    for i in sorted((i for i, _ in chosen), reverse=True):
        batch.lines.insert(i + 1, batch.lines[i])
    batch.save()
    return _entry(SCENARIO_CODES[4], TXN, d, affected=len(chosen),
                  ids=[r["transaction_id"] for _, r in chosen], touched=[(TXN, d, "recomputed")])


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
    return _entry(SCENARIO_CODES[5], TXN, d_txn, affected=len(chosen),
                  ids=[r["transaction_id"] for _, r in chosen],
                  touched=[(TXN, d_txn, "recomputed"), (MERCHANTS, d_dim, "recomputed")],
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
            return _entry(SCENARIO_CODES[6], TXN, d, affected=1, ids=[rec["transaction_id"]],
                          touched=[(TXN, d, "recomputed")],
                          old_customer_id=rec["customer_id"], current_customer_id=new_id)
    raise ChaosError("no transaction of a re-keyed customer within 7 days of the key change")


# ------------------------------------------------ Part B: file-level and schema faults (1.5b)
def s08_resent_file(cfg: GenConfig, root: Path) -> dict:
    """Source retried after a timeout: the same content arrives again as part-0002.jsonl."""
    d = date(2026, 9, 21)
    folder = partition_dir(root, TXN[0], TXN[1], d)
    first, second = folder / "part-0001.jsonl", folder / "part-0002.jsonl"
    shutil.copyfile(first, second)
    lines = first.read_text(encoding="utf-8").splitlines()
    records = [json.loads(x) for x in lines]
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    manifest_path = folder / "_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [{"name": first.name, "records": len(lines), "sha256": digest},
                         {"name": second.name, "records": len(lines), "sha256": digest}]
    manifest["record_count"] = 2 * len(lines)
    manifest["amount_totals"] = _amount_totals(records + records, manifest["amount_field"],
                                               manifest["currency_field"])
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return _entry(SCENARIO_CODES[7], TXN, d, affected=len(lines),
                  touched=[(TXN, d, "recomputed")], resent_as=second.name)


def s09_truncated_upload(cfg: GenConfig, root: Path) -> dict:
    """Upload interrupted: 25% of the file is missing and the last line is cut in half.
    The manifest is NOT updated (transfer defect): counts and checksum no longer match."""
    d = date(2026, 9, 22)
    folder = partition_dir(root, TXN[0], TXN[1], d)
    data = folder / "part-0001.jsonl"
    redelivery = root / CHAOS_DIR / "redelivery" / folder.relative_to(root)
    redelivery.mkdir(parents=True)
    shutil.copyfile(data, redelivery / "part-0001.jsonl")
    shutil.copyfile(folder / "_manifest.json", redelivery / "_manifest.json")
    lines = data.read_text(encoding="utf-8").splitlines()
    keep = len(lines) * 3 // 4
    partial = lines[keep][: len(lines[keep]) // 2]
    with data.open("w", encoding="utf-8", newline="\n") as f:
        f.writelines(line + "\n" for line in lines[:keep])
        f.write(partial)                      # no trailing newline: the stream stopped mid-record
    return _entry(SCENARIO_CODES[8], TXN, d, affected=len(lines) - keep, touched=[(TXN, d, "stale")],
                  expected_records=len(lines), complete_records_delivered=keep,
                  redelivery=redelivery.relative_to(root).as_posix())


def s10_late_file(cfg: GenConfig, root: Path) -> dict:
    """The whole 20 Sep batch arrives late: held in _late/ until explicitly delivered."""
    d = date(2026, 9, 20)
    folder = partition_dir(root, TXN[0], TXN[1], d)
    count = len((folder / "part-0001.jsonl").read_text(encoding="utf-8").splitlines())
    late = root / LATE_DIR / folder.relative_to(root)
    late.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(late))
    return _entry(SCENARIO_CODES[9], TXN, d, affected=count, touched=[(TXN, d, "moved")],
                  moved_to=late.relative_to(root).as_posix())


def s11_added_field(cfg: GenConfig, root: Path) -> dict:
    """ANNOUNCED additive change from 1 Oct: new field device_type, schema_version 1.1."""
    start = date(2026, 10, 1)
    rng = rng_for(cfg.seed, "chaos", "S11")
    count, touched = 0, []
    for d in _existing_days(root, TXN, start):
        batch = Batch.load(root, TXN, d)
        for i, rec in batch.records():
            rec["device_type"] = DEVICE_BY_CHANNEL.get(rec["channel"]) or rng.choice(["ios", "android"])
            batch.lines[i] = _dump(rec)
            count += 1
        batch.save(schema_version="1.1")
        touched.append((TXN, d, "recomputed"))
    return _entry(SCENARIO_CODES[10], TXN, start, affected=count, touched=touched,
                  field="device_type", schema_version="1.1", last_date=touched[-1][1].isoformat())


def s12_renamed_field(cfg: GenConfig, root: Path) -> dict:
    """UNANNOUNCED rename from 9 Nov: merchant_id -> merchant_ref (schema_version not bumped)."""
    start = date(2026, 11, 9)
    count, touched = 0, []
    for d in _existing_days(root, TXN, start):
        batch = Batch.load(root, TXN, d)
        for i, rec in batch.records():
            rec = {("merchant_ref" if k == "merchant_id" else k): v for k, v in rec.items()}
            batch.lines[i] = _dump(rec)
            count += 1
        batch.save()
        touched.append((TXN, d, "recomputed"))
    return _entry(SCENARIO_CODES[11], TXN, start, affected=count, touched=touched,
                  old_field="merchant_id", new_field="merchant_ref", last_date=touched[-1][1].isoformat())


def s13_due_date_format(cfg: GenConfig, root: Path) -> dict:
    """UNANNOUNCED format change from 2 Nov (Stage 6 incident): bill due_date changes from
    'yyyy-mm-dd' to the UTC timestamp of local (Vilnius) midnight, e.g. 2026-11-14T22:00:00Z."""
    start = date(2026, 11, 2)
    count, touched = 0, []
    for d in _existing_days(root, TXN, start):
        batch = Batch.load(root, TXN, d)
        for i, rec in batch.records():
            if rec.get("transaction_type") == "bill_payment" and rec.get("due_date"):
                due = date.fromisoformat(rec["due_date"])
                rec["due_date"] = utc_ts(datetime.combine(due, time(0, 0), tzinfo=VILNIUS))
                batch.lines[i] = _dump(rec)
                count += 1
        batch.save()
        touched.append((TXN, d, "recomputed"))
    return _entry(SCENARIO_CODES[12], TXN, start, affected=count, touched=touched,
                  field="due_date", last_date=touched[-1][1].isoformat())


SCENARIOS = [s01_malformed_json, s02_type_mismatch, s03_missing_business_key, s04_invalid_values,
             s05_duplicates_in_file, s06_late_arriving_dimension, s07_late_fact_old_key,
             s08_resent_file, s09_truncated_upload, s10_late_file, s11_added_field,
             s12_renamed_field, s13_due_date_format]


def apply_chaos(cfg: GenConfig) -> list[dict]:
    """Apply every scenario once and write the log. Refuses if already applied or data is missing."""
    root = cfg.output_root
    for name in (CHAOS_DIR, LATE_DIR):
        if (root / name).exists():
            raise ChaosError(f"{root / name} exists: chaos already applied (or interrupted). "
                             "Regenerate clean data: delete the output folder, then run init and daily.")
    for (source, entity), d in REQUIRED:
        if not (partition_dir(root, source, entity, d) / "part-0001.jsonl").exists():
            raise ChaosError(f"missing {source}/{entity} for {d}: run init and daily through at least 2026-11-09")
    (root / CHAOS_DIR).mkdir(parents=True)
    log = [scenario(cfg, root) for scenario in SCENARIOS]
    (root / CHAOS_DIR / "applied.json").write_text(json.dumps({"scenarios": log}, indent=2) + "\n", encoding="utf-8")
    return log
