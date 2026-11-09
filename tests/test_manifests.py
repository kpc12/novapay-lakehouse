"""Manifests (named _manifest.json) must be readable with plain file I/O."""
from __future__ import annotations

from novapay.common.manifests import manifest_rows


def test_manifest_rows_reads_underscore_files(sim):
    root = sim[1]
    expected = list(root.glob("payments/transactions/*/*/*/_manifest.json"))
    rows = manifest_rows(str(root), "payments/transactions")
    assert len(rows) == len(expected) > 0
    assert all(isinstance(n, int) and n > 0 for _, n in rows)


def test_manifest_listing_names_each_listed_file(sim):
    from novapay.common.manifests import manifest_listing
    root = sim[1]
    listing = manifest_listing(str(root), "payments/transactions")
    assert len(listing) == len(manifest_rows(str(root), "payments/transactions"))   # clean data: one file per batch
    assert all(name == "part-0001.jsonl" for _, _, name in listing)
