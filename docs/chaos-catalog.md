# Chaos catalog (synthetic production faults)

Applied by `python -m data_generator.cli chaos` AFTER `init` and `daily`; exactly once;
every affected record is logged in `data_generator/output/_chaos/applied.json`.
"Expected handling" is the plan; the phase in brackets proves it.

## Part A: record-level faults (Step 1.5a) - manifests recomputed (the source sent this content)
| Code | File / date | Fault | How it happens in production | Expected handling |
|---|---|---|---|---|
| S01_MALFORMED_JSON | payments/transactions 2026-09-08 | 3 lines cut mid-record | Writer crash, partial line flush | Bronze keeps the raw line visible (exact capture verified in Phase 2); Silver quarantines it [Phase 2-3] |
| S02_TYPE_MISMATCH | payments/transactions 2026-09-09 | 2x decimal comma `12,50`, 1x `n/a` amount, 1x `dd/mm/yyyy HH:MM` timestamp | Locale/format drift in the source system | Bronze stores strings; Silver try_cast -> null -> quarantine [Phase 3] |
| S03_MISSING_BUSINESS_KEY | payments/transactions 2026-09-10 | 2x transaction_id = null | Source mapping bug | Quarantine; never invent a key [Phase 3] |
| S04_INVALID_VALUES | payments/transactions 2026-09-11 | currency EUX; negative purchase amount; event_ts in 2027; bill payment without biller | Validation gaps upstream | Quarantine by rule: invalid_currency, negative_amount, future_event_ts, bill_without_biller [Phase 3] |
| S05_DUPLICATES_IN_FILE | payments/transactions 2026-09-14 | 10 records twice in one file | Source retry bug | Bronze count = manifest; Silver dedups on transaction_id before MERGE [Phase 3] |
| S06_LATE_ARRIVING_DIMENSION | transactions 2026-09-16; merchants 2026-09-18 | 3 purchases reference M-90001 two days before its master record | Merchant onboarded in the payment system before the master-data feed | Gold creates an inferred member on 16 Sep, updated in place (Type 1) on 18 Sep [Phase 4] |
| S07_LATE_FACT_OLD_KEY | payments/transactions, first day after 2026-10-15 with a match | 1 transaction with a customer's OLD id after the key change | A system not yet migrated | Silver resolves the old id via key_map to the durable key; no orphan [Phase 3] |

## Part B: file-level and schema faults (Step 1.5b) - planned
S08 resent file, S09 truncated upload (manifest left stale), S10 late file,
S11 added field (schema 1.1), S12 renamed field, S13 due_date format change (Stage 6 incident).
