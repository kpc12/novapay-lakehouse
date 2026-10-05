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

## Step 1.3 additions (schema_version 1.0)
- Manifest: `currency_field` and `amount_totals` (control totals per currency over ALL records,
  including declined; `"ALL"` key when the entity has no currency field)
- acquirer/merchants: country now LT, PL, SE, GB, US (~8% foreign; foreign = online purchases)

## payments/transactions (daily events, partitioned by Europe/Vilnius business date)
Business key: transaction_id (unique; prefix encodes stream: P purchase, R refund,
B bill payment, X transfer out, S salary). Fields: transaction_id, event_ts (UTC),
transaction_type (purchase/refund/bill_payment/transfer_out/salary_in), customer_id, account_id,
payment_method (debit_card/credit_card/mobile_wallet/bank_transfer),
channel (pos/online/mobile_app/web/bank_network), merchant_id, biller_id, bill_reference,
due_date (yyyy-mm-dd), counterparty_iban (PII), original_transaction_id, amount, currency,
status (completed/declined). Non-applicable fields are null.

Rules:
- Amounts are always positive; direction comes from transaction_type
  (debit: purchase, bill_payment, transfer_out; credit: refund, salary_in)
- Refunds are new rows referencing a completed purchase from the previous 1-10 days;
  same customer, account, method, merchant, currency; amount <= original
- credit_card payments use the customer's credit-card account; debit_card and bank_transfer use
  the current account; mobile_wallet uses either
- Customers with kyc_status = expired make no outgoing payments (they can still receive salary/refunds)
- Currency follows merchant country (LT EUR, PL PLN, SE SEK, GB GBP, US USD); transfers, bills, salaries EUR
- Spend metrics exclude bill_payment (see data model rules)

## reference/fx_rates (only on FX publication days)
Fields: rate_date, base_currency (EUR), currency, rate (units per 1 EUR, 4 dp), source.
No file on weekends or fixed-date TARGET closing days (1 Jan, 1 May, 25-26 Dec).
Consumers convert with the latest rate on or before the transaction's business date
(as-of join). Synthetic values - not market data.
