# NovaPay build log

| Step | Decision | Why | Status |
|---|---|---|---|
| 0.1 | Budget alert; regional vCPUs 20; D4ds_v6 / E4ds_v6 | Cost visibility; classic clusters fit quota (DSv2 end-of-life, DDSv5 capacity-blocked) | Done |
| 0.2 | OAuth CLI profiles; no tokens in shell files | Reproducible tooling; env vars override profiles | Done |
| 0.3 | Repo mirrors medallion layers; ADRs | Testable modules; documented decisions | Done |
| 0.4 | ADLS Gen2 (HNS, LRS, TLS 1.2, private); landing + lakehouse | Delta needs real directories; raw vs curated governance | Done |
| 0.5 | Access connector MI, Blob Data Contributor on one account | No keys; least privilege | Done |
| 0.6 | Storage credential + 2 external locations | Unity Catalog governs every path | Done (validate output pending) |
| 0.7 | Catalog novapay_dev, 5 schemas, landing volume | Environment isolation; governed landing | Done (DESCRIBE DETAIL pending) |
| ADR 0003 | Data model v2 | Reconcilable, traceable facts; realistic banking model | Done |
| 1.1 | Source contracts v1.0 | Detect silent source changes | Done |
| 1.2 | Deterministic day-0 master data + tests | Valid parents; real KYC rules | Done |
| 1.3 | Transactions, refunds, bills, salaries, FX | Timezones, as-of FX, refunds as new rows, per-currency totals | Done |
| 1.4 | State engine + daily changes (1.4a / 1.4b) | SCD2, CDC, key_map inputs; consistent transactions | Done (41 tests pass) |
| 1.5a | Record-level chaos S01-S07, logged, once-only | Prove quarantine, dedup, inferred members and key_map catch real faults | Done (53 tests pass) |
| 1.5b | File and schema chaos S08-S13 (resend, truncated upload, late file, added/renamed field, due_date format); band E enabled | Prove reconciliation, rejection, late-data, schema-evolution and Stage 6 handling | Done (59 tests pass; band E = 35) |
| 1.6 | Uploader: date order, manifest last, no overwrites, ledger, late delivery and redelivery as new part (ADR 0004) | Auto Loader ingests each file once; Airflow trusts the manifest | Written |
| 2.1 | Bronze for 12 entities: Auto Loader availableNow, STRING columns, lineage, manifest reconciliation; ADR 0005 directory listing | Bronze keeps exactly what arrived; every batch reconciled | Written |

Details per decision: see docs/decisions/ (ADRs), docs/data-model.md, docs/source-contracts.md.

## Findings and fixes (with evidence)
| Date | Finding | Action |
|---|---|---|
| Step 1.4b | Risk band E could never occur (min score ~365) | Base score for high risk lowered to 400; E = 35, A and B unchanged |
| Step 1.6 | CLI v0.290.1 could not force token refresh (SDK warning) | Upgraded to v1.19.0; re-login required (old token cache rejected by design) |
| Step 1.6 | `validate` by URL refused once an external location covers the path | Validate through the external location; all core operations PASS |
| Step 1.6 | infra/databricks SQL and README were never committed | Recreated and committed (8971626); found via `git ls-files` |
| Step 1.6 | Predictive optimization is ENABLE (inherited from metastore) | Phase 4 retention settings must account for automatic VACUUM |
| Step 1.6 | File-events provisioning fails (identity has data role only) | Decision pending: directory listing vs extra roles (ADR 0005) |
