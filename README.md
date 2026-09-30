# NovaPay Lakehouse

End-to-end batch data platform for a fictional digital bank (NovaPay), built on
Azure Databricks (serverless), Delta Lake on ADLS Gen2, Unity Catalog, Airflow,
GitHub Actions and Snowflake. All data is synthetic.

## Business questions
- Customer transaction analysis across credit, debit, mobile wallet and bank transfers
- Spend and financial habits; bill-payment behaviour for service recommendations
- Credit and investment feature marts; KYC status tracking; customer service usage

## Architecture
_Diagram added in Phase 10._ Medallion layers: Bronze (raw JSON) → Silver (clean, SCD2) → Gold (star schema, marts).

## Progress
- [ ] Phase 0 – Setup
- [ ] Phase 1 – Synthetic data generator
- [ ] Phase 2 – Bronze (Auto Loader)
- [ ] Phase 3 – Silver (DQ, SCD2, CDC)
- [ ] Phase 4 – Gold (star schema, governance)
- [ ] Phase 5 – Idempotency, backfill, reconciliation
- [ ] Phase 6 – Orchestration (Jobs, Airflow)
- [ ] Phase 7 – CI/CD (GitHub Actions)
- [ ] Phase 8 – Snowflake publish
- [ ] Phase 9 – Performance and incident labs
- [ ] Phase 10 – Monitoring and polish

## Decisions
See [docs/decisions](docs/decisions) for Architecture Decision Records.
