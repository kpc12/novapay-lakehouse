# Databricks / Unity Catalog setup (dev)

1. Storage credential (CLI - not available in SQL):
```bash
   AC_ID=$(az databricks access-connector show -g rg-novapay-dev -n ac-novapay-dev --query id -o tsv)
   databricks storage-credentials create --profile novapay --json "{\"name\":\"sc_novapay_dev\",\"azure_managed_identity\":{\"access_connector_id\":\"$AC_ID\"}}"
```
2. Run `01_uc_setup.sql` on serverless compute (notebook or SQL editor).
3. Validate (once external locations exist, validate through them, not the raw URL):
```bash
   databricks storage-credentials validate --profile novapay --json '{"storage_credential_name":"sc_novapay_dev","external_location_name":"el_novapay_landing"}'
```
Note: predictive optimization is inherited as ENABLE from the metastore (automatic OPTIMIZE/VACUUM
on managed tables); retention settings in Phase 4 must account for it.
