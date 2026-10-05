-- NovaPay dev Unity Catalog setup. Prerequisite: storage credential sc_novapay_dev
-- (created via Databricks CLI - see infra/databricks/README.md).
CREATE EXTERNAL LOCATION IF NOT EXISTS el_novapay_landing
  URL 'abfss://landing@stnovapaydev0ea389.dfs.core.windows.net/'
  WITH (STORAGE CREDENTIAL sc_novapay_dev)
  COMMENT 'NovaPay dev - raw JSON files from source systems';

CREATE EXTERNAL LOCATION IF NOT EXISTS el_novapay_lakehouse
  URL 'abfss://lakehouse@stnovapaydev0ea389.dfs.core.windows.net/'
  WITH (STORAGE CREDENTIAL sc_novapay_dev)
  COMMENT 'NovaPay dev - Delta tables (managed location for novapay_dev)';

CREATE CATALOG IF NOT EXISTS novapay_dev
  MANAGED LOCATION 'abfss://lakehouse@stnovapaydev0ea389.dfs.core.windows.net/novapay_dev'
  COMMENT 'NovaPay lakehouse - dev environment';

USE CATALOG novapay_dev;
CREATE SCHEMA IF NOT EXISTS landing COMMENT 'Raw source files (JSON) as delivered';
CREATE SCHEMA IF NOT EXISTS bronze  COMMENT 'Raw, append-only Delta tables + ingestion metadata';
CREATE SCHEMA IF NOT EXISTS silver  COMMENT 'Cleaned, typed, deduplicated, SCD2, quarantine';
CREATE SCHEMA IF NOT EXISTS gold    COMMENT 'Star schema facts/dimensions and business marts';
CREATE SCHEMA IF NOT EXISTS ops     COMMENT 'Pipeline control: batch runs, DQ results, key_map';

CREATE EXTERNAL VOLUME IF NOT EXISTS landing.files
  LOCATION 'abfss://landing@stnovapaydev0ea389.dfs.core.windows.net/files'
  COMMENT 'Landing zone for NovaPay source JSON files';
