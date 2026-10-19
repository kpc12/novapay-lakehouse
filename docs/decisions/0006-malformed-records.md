# ADR 0006: Malformed JSON lines - null row in Bronze, quarantine in Silver

## Status
Accepted

## Context
Step 2.2a delivered 2026-09-08 with three lines cut mid-record (chaos S01). Observed in Bronze:
three rows with every source column null and _rescued_data null; only lineage columns filled.
Reconciliation passed (2930 = 2930) because the broken lines are counted on both sides.
Documentation confirms: PERMISSIVE mode (Auto Loader default) sets malformed fields to null;
_rescued_data only rescues parseable records (type or schema mismatch); columnNameOfCorruptRecord
is ignored by default when Auto Loader rescues data and evolves the schema.

## Decision
- Bronze is unchanged (keeps automatic schema evolution needed for S11/S12).
- Silver quarantines rows whose source columns are all null, reason `malformed_record`,
  keeping _source_file.
- The raw line is recovered on demand from the immutable landing file (ADR 0004).

## Consequences
+ No Bronze redesign; one clear Silver rule.
- Raw text is not stored in the table; it depends on landing files being retained.
  Landing retention must cover the investigation window for quarantined records.
- Count reconciliation proves completeness only; correctness needs Silver rules.
