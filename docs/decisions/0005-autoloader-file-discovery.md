# ADR 0005: Auto Loader file discovery - directory listing, data-only identity

## Status
Accepted (revisit in Phase 9 performance labs)

## Context
`storage-credentials validate` on el_novapay_landing passed READ, LIST, WRITE, DELETE,
PATH_EXISTS and HIERARCHICAL_NAMESPACE_ENABLED, but file-events provisioning failed (403).
New external locations have file events enabled by default; provisioning needs the identity to
hold Storage Account Contributor, EventGrid EventSubscription Contributor and Storage Queue Data
Contributor in addition to Storage Blob Data Contributor. Our access connector deliberately has
only Storage Blob Data Contributor (least privilege, Step 0.5). Databricks recommends file
events at scale; directory listing is documented for small directories or when security policy
prevents file events. Our landing area receives ~30 small batches per day.

## Decision
Auto Loader uses directory listing: `cloudFiles.useManagedFileEvents = false` set explicitly in
every Bronze stream. The access connector stays data-only. File events are disabled on the
external locations so they are not left half-provisioned.

## Consequences
+ Identity cannot manage the storage account (Storage Account Contributor is broad).
+ Behaviour is explicit, not dependent on defaults.
- Each run lists the landing directories; cost and time grow with directory size.
- Phase 9 will measure directory listing vs file events before any change.

## Follow-up (inspection result)
`external-locations get el_novapay_landing` showed effective_enable_file_events = true with a
managed Azure Queue Storage configuration, while provisioning had failed (403): a half-configured
state. File events were disabled on el_novapay_landing and el_novapay_lakehouse; validate now
passes. Streams also set cloudFiles.useManagedFileEvents = false, so behaviour stays explicit.
