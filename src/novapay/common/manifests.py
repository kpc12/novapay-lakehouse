"""Read batch manifests with plain file I/O.

Spark file readers skip names starting with '_' (treated as hidden/metadata files), so
_manifest.json cannot be read with spark.read. On Databricks, /Volumes paths are readable as
regular files, and manifests are tiny, so plain Python is the right tool."""
from __future__ import annotations

import glob
import json
import os


def manifest_rows(landing_root: str, subpath: str) -> list[tuple[str, int]]:
    """(business_date, record_count) for every delivered batch of one entity."""
    pattern = os.path.join(landing_root, subpath, "*", "*", "*", "_manifest.json")
    rows = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        rows.append((manifest["business_date"], int(manifest["record_count"])))
    return rows
