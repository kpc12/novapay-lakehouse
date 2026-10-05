"""Deliver generated files to the landing volume (Step 1.6).

Delivery protocol (ADR 0004):
- batches go in business-date order; inside a batch, data files first and _manifest.json LAST
- data files are never overwritten (Auto Loader ingests each file once by default)
- a redelivery is a NEW part file plus a manifest with delivery_attempt and supersedes
- folders whose name starts with '_' (_chaos, _late, _uploads) are never part of normal delivery
Every successful upload is appended to <output>/_uploads/ledger.jsonl, so reruns are idempotent."""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

LANDING_VOLUME = "/Volumes/novapay_dev/landing/files"
MANIFEST = "_manifest.json"
SOURCE_ORDER = ["core_banking", "acquirer", "reference", "kyc_vendor", "payments", "crm",
                "custodian", "credit_bureau"]


class UploadError(RuntimeError):
    """Delivery would break the protocol (overwrite, unknown landing content, wrong order)."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Target(Protocol):
    def list_files(self, remote_dir: str) -> set[str] | None: ...
    def mkdir(self, remote_dir: str) -> None: ...
    def put(self, remote_path: str, data: bytes, overwrite: bool) -> None: ...


class LocalTarget:
    """A local folder standing in for the volume; records every upload in order (tests, rehearsal)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str] = []

    def _path(self, remote: str) -> Path:
        return self.root / remote.lstrip("/")

    def list_files(self, remote_dir: str) -> set[str] | None:
        p = self._path(remote_dir)
        return {x.name for x in p.iterdir() if x.is_file()} if p.is_dir() else None

    def mkdir(self, remote_dir: str) -> None:
        self._path(remote_dir).mkdir(parents=True, exist_ok=True)

    def put(self, remote_path: str, data: bytes, overwrite: bool) -> None:
        p = self._path(remote_path)
        if p.exists() and not overwrite:
            raise UploadError(f"{remote_path} already exists")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.calls.append(remote_path)


class VolumeTarget:
    """Unity Catalog volume through the Databricks SDK Files API; auth from a CLI profile (OAuth)."""

    def __init__(self, profile: str) -> None:
        from databricks.sdk import WorkspaceClient   # imported lazily: tests do not need the SDK
        self.w = WorkspaceClient(profile=profile)

    def list_files(self, remote_dir: str) -> set[str] | None:
        from databricks.sdk.errors import NotFound
        try:
            return {(e.name or e.path.rsplit("/", 1)[-1])
                    for e in self.w.files.list_directory_contents(remote_dir) if not e.is_directory}
        except NotFound:
            return None

    def mkdir(self, remote_dir: str) -> None:
        self.w.files.create_directory(remote_dir)

    def put(self, remote_path: str, data: bytes, overwrite: bool) -> None:
        self.w.files.upload(remote_path, io.BytesIO(data), overwrite=overwrite)


class Ledger:
    """Append-only record of every upload (path, sha256, kind); survives interruptions."""

    def __init__(self, output_root: Path) -> None:
        self.path = output_root / "_uploads" / "ledger.jsonl"
        self.digests: dict[str, str] = {}
        self.redelivered_dirs: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                self._apply(entry["path"], entry["sha256"], entry["kind"])

    def _apply(self, remote_path: str, digest: str, kind: str) -> None:
        self.digests[remote_path] = digest
        if kind == "redelivery":
            self.redelivered_dirs.add(remote_path.rsplit("/", 1)[0])

    def record(self, remote_path: str, digest: str, kind: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"path": remote_path, "sha256": digest, "kind": kind}) + "\n")
        self._apply(remote_path, digest, kind)


@dataclass(frozen=True)
class FoundBatch:
    source: str
    entity: str
    business_date: date
    folder: Path

    @property
    def rel_dir(self) -> str:
        return f"{self.source}/{self.entity}/{self.business_date:%Y/%m/%d}"


@dataclass
class Result:
    batches: int = 0
    files: int = 0
    skipped_batches: int = 0


def find_batches(base: Path, start: date | None = None, end: date | None = None) -> list[FoundBatch]:
    """Complete batches (folders WITH a manifest) under base, in delivery order."""
    rank = {s: i for i, s in enumerate(SOURCE_ORDER)}
    found = []
    for manifest in base.glob(f"*/*/*/*/*/{MANIFEST}"):
        source, entity, y, m, d = manifest.parent.relative_to(base).parts
        if source.startswith("_") or entity.startswith("_"):
            continue
        business_date = date(int(y), int(m), int(d))
        if (start and business_date < start) or (end and business_date > end):
            continue
        found.append(FoundBatch(source, entity, business_date, manifest.parent))
    return sorted(found, key=lambda b: (b.business_date, rank.get(b.source, len(rank)), b.source, b.entity))


def _batch_files(folder: Path) -> list[tuple[str, bytes]]:
    data = sorted(p for p in folder.iterdir() if p.is_file() and p.name != MANIFEST)
    if not data:
        raise UploadError(f"{folder} has a manifest but no data file")
    return [(p.name, p.read_bytes()) for p in data] + [(MANIFEST, (folder / MANIFEST).read_bytes())]


def _deliver(target: Target, ledger: Ledger, remote_dir: str, files: list[tuple[str, bytes]],
             kind: str, overwrite_manifest: bool = False) -> int:
    """Upload files (manifest LAST in the list). Skips content already delivered; refuses to
    overwrite anything else. Returns the number of files uploaded."""
    existing = target.list_files(remote_dir) or set()
    pending = []
    for name, data in files:
        remote_path = f"{remote_dir}/{name}"
        digest = _sha(data)
        if ledger.digests.get(remote_path) == digest:
            continue
        replacing_manifest = name == MANIFEST and overwrite_manifest
        if (remote_path in ledger.digests or name in existing) and not replacing_manifest:
            raise UploadError(f"{remote_path} is already in landing with different or unknown content. "
                              "Data files are never overwritten (ADR 0004); reset the landing area to start over.")
        pending.append((remote_path, data, digest, replacing_manifest))
    if pending:
        target.mkdir(remote_dir)
    for remote_path, data, digest, replacing in pending:
        target.put(remote_path, data, overwrite=replacing)
        ledger.record(remote_path, digest, kind)
    return len(pending)


def _deliver_all(target: Target, output_root: Path, base: Path, remote_base: str,
                 kind: str, start: date | None = None, end: date | None = None) -> Result:
    ledger, result = Ledger(output_root), Result()
    for b in find_batches(base, start, end):
        remote_dir = f"{remote_base}/{b.rel_dir}"
        if remote_dir in ledger.redelivered_dirs:      # superseded by a redelivery: leave as is
            result.skipped_batches += 1
            continue
        n = _deliver(target, ledger, remote_dir, _batch_files(b.folder), kind)
        if n:
            result.batches += 1
            result.files += n
        else:
            result.skipped_batches += 1
    return result


def upload(target: Target, output_root: Path, remote_base: str = LANDING_VOLUME,
           start: date | None = None, end: date | None = None) -> Result:
    """Normal daily delivery for business dates start..end (inclusive; None = open-ended)."""
    return _deliver_all(target, output_root, output_root, remote_base, "delivery", start, end)


def deliver_late(target: Target, output_root: Path, remote_base: str = LANDING_VOLUME) -> Result:
    """Deliver batches held back in _late/ to their normal landing paths (S10)."""
    return _deliver_all(target, output_root, output_root / "_late", remote_base, "late")


def redeliver(target: Target, output_root: Path, remote_base: str = LANDING_VOLUME) -> Result:
    """Redeliver the intact originals in _chaos/redelivery/ (S09) as a NEW part file plus a
    manifest with delivery_attempt and supersedes. The original must already be in landing."""
    ledger, result = Ledger(output_root), Result()
    for b in find_batches(output_root / "_chaos" / "redelivery"):
        remote_dir = f"{remote_base}/{b.rel_dir}"
        data = (b.folder / "part-0001.jsonl").read_bytes()
        digest = _sha(data)
        if any(p.startswith(remote_dir + "/") and s == digest for p, s in ledger.digests.items()):
            result.skipped_batches += 1                 # this content was already redelivered
            continue
        existing = target.list_files(remote_dir)
        if not existing or MANIFEST not in existing:
            raise UploadError(f"{remote_dir}: deliver the original batch before redelivering it")
        parts = sorted(n for n in existing if n.startswith("part-") and n.endswith(".jsonl"))
        name = f"part-{len(parts) + 1:04d}.jsonl"
        manifest = json.loads((b.folder / MANIFEST).read_text(encoding="utf-8"))
        manifest["files"] = [{"name": name, "records": len(data.splitlines()), "sha256": digest}]
        manifest["delivery_attempt"] = len(parts) + 1
        manifest["supersedes"] = parts
        payload = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        result.files += _deliver(target, ledger, remote_dir, [(name, data), (MANIFEST, payload)],
                                 "redelivery", overwrite_manifest=True)
        result.batches += 1
    return result
