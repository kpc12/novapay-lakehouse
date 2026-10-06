# Databricks notebook source
# MAGIC %md
# MAGIC # Bronze ingestion - Phase 2, Step 2.1
# MAGIC Ingests every delivered source entity into `bronze.<entity>` with Auto Loader (availableNow),
# MAGIC then reconciles Bronze row counts with each batch manifest (results kept in `ops.bronze_reconciliation`).

# COMMAND ----------

dbutils.widgets.text("catalog", "novapay_dev")
catalog = dbutils.widgets.get("catalog")

# COMMAND ----------

import os
import sys
import uuid

root = os.path.abspath(os.getcwd())
while root != "/" and not os.path.isdir(os.path.join(root, "src", "novapay")):
    root = os.path.dirname(root)
sys.path.insert(0, os.path.join(root, "src"))

from novapay.bronze.ingest import ingest, reconcile
from novapay.common.sources import SOURCE_ENTITIES

landing_root = f"/Volumes/{catalog}/landing/files"
checkpoint_root = f"/Volumes/{catalog}/ops/checkpoints/bronze"
run_id = str(uuid.uuid4())
print("repo root:", root, "| run_id:", run_id)

# COMMAND ----------

ingested = []
for se in SOURCE_ENTITIES:
    try:
        dbutils.fs.ls(f"{landing_root}/{se.landing_subpath}")
    except Exception:
        print(f"skip {se.entity}: nothing delivered yet")
        continue
    ingest(spark, catalog, landing_root, checkpoint_root, se, run_id)
    ingested.append(se)
    print(f"ingested {se.entity}")

# COMMAND ----------

from functools import reduce

results = reduce(lambda a, b: a.unionByName(b),
                 [reconcile(spark, catalog, landing_root, se, run_id) for se in ingested])
results.write.mode("append").saveAsTable(f"{catalog}.ops.bronze_reconciliation")
display(results.orderBy("entity", "batch_date"))

# COMMAND ----------

checked = results.count()
mismatches = results.filter("status <> 'OK'").count()
print(f"batches checked: {checked} | mismatches: {mismatches}")
assert mismatches == 0, "Bronze does not match the manifests - investigate before continuing"
