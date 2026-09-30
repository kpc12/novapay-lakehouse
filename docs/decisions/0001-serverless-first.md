# ADR 0001: Serverless compute first

## Status
Accepted

## Context
Personal Azure subscription (pay-as-you-go, Premium Databricks workspace, East US);
cost and setup time matter. Databricks recommends serverless compatibility for new workloads.

## Decision
Run notebooks and jobs on serverless compute. Classic compute only for
optional Spark UI / autoscaling labs, if quota allows.

## Consequences
+ No cluster management, fast start, pay per use.
- No Spark UI (use Query Profile), most Spark configs cannot be set,
  no DataFrame caching. AQE/speculation/autoscaling are learned conceptually
  unless a classic cluster is used.
- Classic quota in East US: 10 regional vCPUs, DSv2 family 10, spot 3 → classic
  labs limited to single node or driver + 1 worker (Standard_DS3_v2), on-demand only.
