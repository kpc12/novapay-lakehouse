"""Bronze ingestion with Auto Loader (Phase 2, Step 2.1).

Every source entity lands in bronze.<entity> exactly as delivered: all columns STRING,
unexpected fields in _rescued_data, plus lineage columns. File discovery uses directory listing
(ADR 0005). Each run is a batch: trigger(availableNow=True) processes all new files and stops;
the checkpoint guarantees each file is ingested once."""
from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from novapay.common.manifests import manifest_rows
from novapay.common.sources import BATCH_DATE_PATTERN, SourceEntity


def read_landing(spark: SparkSession, landing_root: str, checkpoint: str, se: SourceEntity) -> DataFrame:
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "json")
            .option("cloudFiles.schemaLocation", checkpoint)
            .option("cloudFiles.inferColumnTypes", "false")         # every column lands as STRING
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
            .option("cloudFiles.useManagedFileEvents", "false")     # ADR 0005: directory listing
            .option("pathGlobFilter", "*.jsonl")                     # manifests are control files
            .load(f"{landing_root}/{se.landing_subpath}/"))


def add_lineage(df: DataFrame, run_id: str) -> DataFrame:
    path = F.col("_metadata.file_path")
    batch_date = F.concat_ws("-", *(F.regexp_extract(path, BATCH_DATE_PATTERN, i) for i in (1, 2, 3)))
    return df.select(
        "*",
        path.alias("_source_file"),
        F.col("_metadata.file_modification_time").alias("_file_modification_time"),
        F.to_date(batch_date).alias("_batch_date"),
        F.current_timestamp().alias("_ingest_ts"),
        F.lit(run_id).alias("_run_id"),
    )


def ingest(spark: SparkSession, catalog: str, landing_root: str, checkpoint_root: str,
           se: SourceEntity, run_id: str) -> None:
    """Ingest all new files of one entity, then stop (batch semantics, exactly-once per file)."""
    checkpoint = f"{checkpoint_root}/{se.entity}"
    query = (add_lineage(read_landing(spark, landing_root, checkpoint, se), run_id)
             .writeStream
             .queryName(f"bronze_{se.entity}")             # visible in spark.streams.active
             .option("checkpointLocation", checkpoint)
             .option("mergeSchema", "true")                         # Bronze table evolves with new columns
             .trigger(availableNow=True)
             .toTable(f"{catalog}.{se.bronze_table}"))
    query.awaitTermination()


def reconcile(spark: SparkSession, catalog: str, landing_root: str, se: SourceEntity, run_id: str) -> DataFrame:
    """Bronze rows per batch date vs. the manifest's record_count. Manifests are read with plain
    Python (Spark skips '_' files). Missing counts mean 0, so empty change files reconcile as 0 = 0."""
    manifests = (spark.createDataFrame(manifest_rows(landing_root, se.landing_subpath),
                                       "business_date STRING, manifest_records LONG")
                 .select(F.to_date("business_date").alias("batch_date"), "manifest_records"))
    bronze = (spark.table(f"{catalog}.{se.bronze_table}")
              .groupBy(F.col("_batch_date").alias("batch_date"))
              .agg(F.count(F.lit(1)).alias("bronze_records")))
    manifest_n = F.coalesce(F.col("manifest_records"), F.lit(0))
    bronze_n = F.coalesce(F.col("bronze_records"), F.lit(0))
    return (manifests.join(bronze, "batch_date", "full_outer")
            .select(F.lit(se.entity).alias("entity"), "batch_date",
                    manifest_n.alias("manifest_records"), bronze_n.alias("bronze_records"),
                    F.when(manifest_n == bronze_n, "OK").otherwise("MISMATCH").alias("status"),
                    F.lit(run_id).alias("run_id"), F.current_timestamp().alias("checked_at")))
