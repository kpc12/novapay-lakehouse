# NovaPay source data contracts (synthetic) — schema_version 1.0

## Delivery conventions
- Format: JSON Lines, UTF-8. Path: `<source>/<entity>/yyyy/mm/dd/part-0001.jsonl`
- `_manifest.json` in the same folder, written LAST (= batch complete). Fields: schema_version,
  source, entity, business_date, files[name, records, sha256], record_count, amount_field,
  amount_total (sum of parseable amounts), generated_at
- Consumers read ONLY `*.jsonl` (Auto Loader `pathGlobFilter`); manifests are control files
- Upload order: data files first, manifest last
- A rerun of a business date replaces the whole partition folder
- Money: strings with 2 decimals. Timestamps: ISO-8601 UTC (`...Z`). Dates: `yyyy-mm-dd`
- Master data = change records: `op` (I/U/D), `change_seq`, `change_ts`.
  `change_seq = yyyymmdd * 10,000,000 + n` (strictly increasing across days; order by it)
- Reference data = full daily snapshots

## Entities
| Source/entity | Delivery | Business key | Fields | PII |
|---|---|---|---|---|
| core_banking/customers | change records | customer_id | op, change_seq, change_ts, customer_id, old_customer_id (key change only), first_name, last_name, email, phone, date_of_birth, city, country (LT/LV/EE), segment (mass/affluent/premium), kyc_status (verified/pending/expired), risk_rating (low/medium/high), customer_since | first_name, last_name, email, phone, date_of_birth |
| core_banking/accounts | change records | account_id | op, change_seq, change_ts, account_id, account_type (current/savings/credit_card), status, currency, open_date, credit_limit (credit_card only, else null) | – |
| core_banking/account_holders | change records | (account_id, customer_id) | op, change_seq, change_ts, account_id, customer_id, role (primary/joint) | – |
| acquirer/merchants | change records | merchant_id | op, change_seq, change_ts, merchant_id, merchant_name, mcc, category, city, country | – |
| reference/billers | full snapshot | biller_id | biller_id, biller_name, bill_type (utility/telecom/internet/insurance/rent) | – |
| reference/invest_products | full snapshot | isin | isin (synthetic, ISIN-like), product_name, asset_class, risk_level (SRI 1–7), currency | – |

## Business rules
- Every customer has one current account, opened on customer_since
- Savings / credit-card accounts open between customer_since and the day before the start date
- Credit cards and joint holders only for kyc_status = verified; a joint holder differs from the primary
- Phone prefix by country: LT +3706, LV +3712, EE +3725
- Transactions and other daily feeds: defined in Step 1.3
