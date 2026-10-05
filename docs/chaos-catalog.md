# Chaos catalog (synthetic production faults)

Applied by `python -m data_generator.cli chaos` AFTER `init` and `daily` (through at least 2026-11-09);
exactly once; logged in `data_generator/output/_chaos/applied.json` with every touched file and its
manifest state: `recomputed` (source defect: manifest describes the file), `stale` (transfer defect:
manifest no longer matches), `moved` (late file held in `_late/`).
"Expected handling" is the plan; the phase in brackets proves it.

## Part A: record-level faults (Step 1.5a)
| Code | File / date | Fault | How it happens in production | Expected handling |
|---|---|---|---|---|
| S01_MALFORMED_JSON | transactions 2026-09-08 | 3 lines cut mid-record | Writer crash, partial flush | Bronze keeps the raw line visible (exact capture verified in Phase 2); Silver quarantines [Phase 2-3] |
| S02_TYPE_MISMATCH | transactions 2026-09-09 | 2x decimal comma `12,50`, 1x `n/a`, 1x `dd/mm/yyyy HH:MM` timestamp | Locale/format drift | Bronze strings; Silver try_cast -> null -> quarantine [Phase 3] |
| S03_MISSING_BUSINESS_KEY | transactions 2026-09-10 | 2x transaction_id null | Source mapping bug | Quarantine; never invent a key [Phase 3] |
| S04_INVALID_VALUES | transactions 2026-09-11 | currency EUX; negative purchase; event_ts 2027; bill without biller | Upstream validation gaps | Quarantine by named rule [Phase 3] |
| S05_DUPLICATES_IN_FILE | transactions 2026-09-14 | 10 records twice | Source retry bug | Bronze = manifest; Silver dedups before MERGE [Phase 3] |
| S06_LATE_ARRIVING_DIMENSION | transactions 2026-09-16; merchants 2026-09-18 | 3 purchases reference M-90001 before its master record | Merchant onboarded in payments before master data | Inferred member, updated in place (Type 1) when master arrives [Phase 4] |
| S07_LATE_FACT_OLD_KEY | transactions 2026-10-16 | 1 transaction with a pre-migration customer id | System not yet migrated | Resolve via key_map to the durable key [Phase 3] |

## Part B: file-level and schema faults (Step 1.5b)
| Code | File / date | Fault | Manifest | Expected handling |
|---|---|---|---|---|
| S08_RESENT_FILE | transactions 2026-09-21 | Same content again as part-0002.jsonl | recomputed (2 files, same sha256) | Identical checksums reveal a duplicate file; Bronze ingests both paths; Silver dedups [Phase 2-3] |
| S09_TRUNCATED_UPLOAD | transactions 2026-09-22 | 25% missing, last line cut | **stale** | Count/checksum mismatch -> reject the whole batch, alert; redeliver from `_chaos/redelivery/` and reprocess idempotently [Phase 2, 5] |
| S10_LATE_FILE | transactions 2026-09-20 | Whole batch held in `_late/` | moved with the file | Manifest sensor times out and alerts; on late delivery, process the date and rebuild affected aggregates. Refunds of 20 Sep purchases arrive BEFORE their originals [Phase 3, 5, 6] |
| S11_ADDED_FIELD | transactions from 2026-10-01 | New field `device_type` | recomputed, schema_version **1.1** (announced) | Auto Loader addNewColumns (stop + restart); Silver ignores it until the contract change is approved [Phase 2-3] |
| S12_RENAMED_FIELD | transactions from 2026-11-09 | `merchant_id` -> `merchant_ref`, version NOT bumped | recomputed | New column in Bronze; old column null for new rows; null-rate alert; Silver maps coalesce(merchant_ref, merchant_id) [Phase 2-3] |
| S13_DUE_DATE_FORMAT | transactions from 2026-11-02 (bill payments) | `due_date` becomes UTC timestamp of Vilnius midnight, version NOT bumped (Stage 6 incident) | recomputed | Format check flags it; correct parsing converts to Europe/Vilnius before taking the date (DST-aware) [Phase 3] |

## Reconciliation expectations
- S05: Bronze rows = manifest record_count; Silver distinct = manifest - 10 duplicates.
- S08: Bronze rows = 2 x file rows; Silver distinct = file rows.
- S09: never load partially: the batch is rejected until the redelivered file matches its manifest.
- Generated credit_bureau `days_past_due_max` comes from clean bill payments, so Silver's lateness
  computed from S13 data must match it only when due_date is parsed correctly.

## Upload rules (Step 1.6)
`_chaos/` and `_late/` are never uploaded as part of normal daily delivery; late delivery and redelivery
are explicit, separate actions.
