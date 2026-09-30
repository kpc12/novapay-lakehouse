#!/usr/bin/env bash
# NovaPay dev infrastructure (Azure side). Safe to re-run.
set -euo pipefail

RG="rg-novapay-dev"
LOCATION="eastus"
SA_NAME="stnovapaydev0ea389"      # <-- your unique name
AC_NAME="ac-novapay-dev"
TAGS="project=novapay env=dev owner=kaustubh"

echo ">> Resource group"
az group create --name "$RG" --location "$LOCATION" --tags $TAGS -o none

echo ">> ADLS Gen2 storage account (hierarchical namespace on)"
az storage account create \
  --name "$SA_NAME" --resource-group "$RG" --location "$LOCATION" \
  --sku Standard_LRS --kind StorageV2 --hns true \
  --min-tls-version TLS1_2 --allow-blob-public-access false \
  --tags $TAGS -o none

echo ">> Containers"
for c in landing lakehouse; do
  az storage container-rm create --storage-account "$SA_NAME" \
    --resource-group "$RG" --name "$c" -o none
done

echo "Done: storage account $SA_NAME with containers landing, lakehouse"

echo ">> Access connector for Azure Databricks (system-assigned managed identity)"
az databricks access-connector create \
  --resource-group "$RG" --name "$AC_NAME" --location "$LOCATION" \
  --identity-type SystemAssigned --tags $TAGS -o none

PRINCIPAL_ID=$(az databricks access-connector show -g "$RG" -n "$AC_NAME" --query identity.principalId -o tsv)
SA_ID=$(az storage account show -g "$RG" -n "$SA_NAME" --query id -o tsv)

echo ">> Grant Storage Blob Data Contributor to the access connector on the storage account"
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope "$SA_ID" -o none || \
  echo "   (role assignment may already exist - check with az role assignment list)"

echo "Access connector resource ID (needed for the Unity Catalog storage credential):"
az databricks access-connector show -g "$RG" -n "$AC_NAME" --query id -o tsv
