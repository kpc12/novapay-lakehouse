# ADR 0004: Landing delivery protocol (no overwrites, manifest last, redelivery as new file)

## Status
Accepted

## Context
Auto Loader, with its recommended default cloudFiles.allowOverwrites = false, processes each file
exactly once; when a file is overwritten it cannot guarantee which version is processed. Airflow
(Phase 6) treats a batch's manifest as the "batch complete" signal. Generated data can be
regenerated locally, which must never silently change files already in landing.

## Decision
- Deliver batches in business-date order; inside a batch, data files first, _manifest.json last.
- Never overwrite a data file in landing. Changed or unknown content is refused.
- A redelivery adds a NEW part file and replaces the manifest with one that lists only the new
  file and carries delivery_attempt and supersedes. Consumers process the files listed in the
  latest manifest.
- Folders starting with '_' (_chaos, _late, _uploads) are never part of normal delivery; late
  delivery and redelivery are explicit commands.
- Every upload is recorded in an append-only ledger (path, sha256, kind) for idempotent reruns.
- Upload via the Databricks SDK Files API using the CLI OAuth profile (no tokens).

## Consequences
+ Auto Loader never misses corrected data; reruns are safe; delivery order is guaranteed.
- Superseded files stay in landing and Bronze; Silver must select files by the latest manifest.
- Regenerating data after delivery requires an explicit landing reset.
