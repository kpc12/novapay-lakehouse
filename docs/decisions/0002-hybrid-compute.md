# ADR 0002: Hybrid compute – serverless for development, classic job clusters for tuning

## Status
Accepted

## Context
Serverless hides node types, worker counts, autoscaling and the Spark UI, which are
needed to demonstrate and explain executor sizing. East US quotas: Total Regional
vCPUs 20 (increased from 10); current-generation families (e.g. Ddsv6, Edsv6) 10 each;
spot (low-priority) 3.

## Decision
Develop on serverless. Run scheduled pipelines and performance labs on classic job
clusters defined in Databricks Asset Bundles, on-demand VMs only.
Node types: Standard_D4ds_v6 (4 cores / 16 GB) and Standard_E4ds_v6 (4 cores / 32 GB).
Driver and workers use different families so autoscaling (1–2 workers) fits within
per-family quotas of 10 vCPUs and a regional quota of 20.
Rejected: DSv2 (end-of-life, quota not adjustable); DDSv5 (capacity-constrained in
East US, quota unavailable). Fallback: Dadsv7 / Eadsv7.

## Consequences
+ Hands-on executor sizing, autoscaling and Spark UI analysis.
+ Job clusters bill at the lower jobs-compute rate and terminate after each run.
- Cluster start-up adds a few minutes per run; VM + DBU cost while running.
- Quota does not guarantee regional capacity; a cluster start can still fail.
- No spot instances (low-priority quota 3 < one 4-core VM).
