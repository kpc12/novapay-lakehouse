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

## Step 1.4a additions (schema_version 1.0)
- Change files (customers, accounts, account_holders, merchants) are delivered EVERY day from
  day 1, even when empty: empty file + manifest (record_count 0) = "no changes today".
- I/U records carry the full row after the change; D records carry the last known row.
- Key change: op U with the NEW customer_id and old_customer_id set (only on that record);
  holdings of the old id arrive as D (old id) + I (new id). Later events use the new id;
  refunds of earlier purchases carry the new id (resolve via key_map).
- Account closure = op U with status closed (never a delete); closed accounts stop transacting.
- Joint-holder removal = op D on account_holders.
- reference/billers and reference/invest_products: full snapshot every day; a missing key
  means deleted (only trust this after the snapshot passes a completeness check).
- Scenario dates: 2026-10-05 biller B-011 added; 2026-10-15 key change (3 customers);
  2026-10-25 DST change in Vilnius; 2026-11-02 NPX000000009 risk_level 6 -> 7;
  2026-11-16 biller B-010 removed.

## Known simplifications (synthetic data)
- kyc_status = pending customers can make payments (only expired is blocked)
- Investment purchases do not appear as cash transactions
- Foreign merchants are online-only; transfers, bills and salaries are always EUR
- New customers start as mass segment, medium risk, KYC pending

## Step 1.4b additions (schema_version 1.0)

### kyc_vendor/kyc_checks (daily events from day 1; may be empty)
Key: kyc_check_id. Fields: kyc_check_id, check_ts (UTC), customer_id,
check_type (identity_document/periodic_review/re_verification), result (pass/fail/review), provider.
Rule: a check that changes kyc_status comes with a customers op U on the same day (change_ts = check_ts).
pending -> verified on pass; verified -> expired on failed periodic review; expired -> verified on passed re-verification.

### custodian/holdings (TARGET business days only; end-of-day positions)
Key: (business_date, customer_id, isin). Fields: business_date, customer_id, isin, units (4 dp),
price (4 dp), market_value (2 dp), currency. Manifest totals on market_value.
Illustrative suitability rule: product risk_level <= 3 / 5 / 7 for risk_rating low / medium / high.

### crm/support_cases (daily change records from day 1; accumulating-snapshot input)
Key: case_id. Fields: op, change_seq, change_ts, case_id, customer_id, channel (chat/phone/email),
reason (declined_payment/card_issue/login_problem/fee_question/transfer_status),
status (opened/in_progress/resolved), opened_ts, first_response_ts, resolved_ts.
Lifecycle: opened (I) -> in_progress (U, 1-2 days later) -> resolved (U, 1-5 days later).
Updates carry the current customer id. Cases are much more likely on days with a declined payment.

### credit_bureau/credit_scores (first TARGET business day of each month, for the previous month)
Key: (report_month, customer_id). Fields: report_month (yyyy-mm), customer_id,
score (integer 1-999, invented scale), risk_band (A >= 800, B >= 650, C >= 500, D >= 350, else E),
open_credit_lines, days_past_due_max (max days late of bill payments paid in report_month), bureau.

### More known simplifications
- Newly verified customers do not receive credit cards; new customers never invest
- Score scale, bands and suitability rule are invented for the project, not taken from a real bureau or regulation

## Deliberate contract violations
Synthetic production faults are injected on purpose by the `chaos` command; see docs/chaos-catalog.md.

## Contract version history
- 1.0 (2026-09-01): initial contract
- 1.1 (announced, effective 2026-10-01): payments/transactions adds field `device_type`
  (pos_terminal / web_browser / bank_system / ios / android). Additive; existing fields unchanged.
Unannounced changes (S12 rename, S13 due_date format) are contract VIOLATIONS: see docs/chaos-catalog.md.

## Delivery protocol (ADR 0004)
- Batches arrive in business-date order; data files first, _manifest.json last.
- Data files are immutable once delivered. A redelivery is a new part file; the replacement
  manifest lists only that file and adds `delivery_attempt` and `supersedes`.
- Late batches arrive later in their normal business-date path.
