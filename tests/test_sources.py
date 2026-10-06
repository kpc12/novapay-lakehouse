"""The Bronze source registry must match what the generator delivers."""
from __future__ import annotations

import re
from datetime import date

from novapay.common.sources import BATCH_DATE_PATTERN, SOURCE_ENTITIES


def test_every_generated_entity_has_a_bronze_mapping(sim):
    root = sim[1]
    generated = {(p.parent.name, p.name) for p in root.glob("*/*")
                 if p.is_dir() and not p.parent.name.startswith("_")}
    assert generated == {(se.source, se.entity) for se in SOURCE_ENTITIES}


def test_bronze_table_names_are_unique():
    tables = [se.bronze_table for se in SOURCE_ENTITIES]
    assert len(tables) == len(set(tables))


def test_batch_date_pattern_extracts_partition_date():
    path = "dbfs:/Volumes/novapay_dev/landing/files/payments/transactions/2026/09/21/part-0002.jsonl"
    m = re.search(BATCH_DATE_PATTERN, path)
    assert date(int(m.group(1)), int(m.group(2)), int(m.group(3))) == date(2026, 9, 21)
