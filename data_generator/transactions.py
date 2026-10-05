"""Daily payment transactions and FX rates (Step 1.3; refactored in 1.4a to read daily state)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from random import Random
from zoneinfo import ZoneInfo

from .common import money, rng_for, utc_ts
from .config import GenConfig
from .state import ALL_BILLERS, DayView, resolve_customer

VILNIUS = ZoneInfo("Europe/Vilnius")
CURRENCY_BY_COUNTRY = {"LT": "EUR", "PL": "PLN", "SE": "SEK", "GB": "GBP", "US": "USD"}
# Synthetic FX starting levels (units of currency per 1 EUR). Illustrative only - NOT market data.
FX_BASE = {"GBP": Decimal("0.85"), "PLN": Decimal("4.30"), "SEK": Decimal("11.20"), "USD": Decimal("1.10")}
# Fixed-date TARGET closing days; Good Friday / Easter Monday fall outside the Sep-Dec 2026 window.
FX_FIXED_CLOSING_DAYS = {(1, 1), (5, 1), (12, 25), (12, 26)}
# --- Synthetic assumptions (invented for realism, not real statistics) ---
AMOUNT_RANGE_EUR = {"Groceries": (3, 120), "Restaurants": (8, 90), "Fast Food": (3, 25), "Fuel": (20, 90),
                    "Pharmacy": (3, 60), "Electronics": (20, 900), "Clothing": (10, 250),
                    "Taxi": (4, 35), "Cinema": (6, 30)}
BILL_RANGE = {"utility": (20, 150), "telecom": (10, 40), "internet": (15, 35),
              "insurance": (20, 80), "rent": (300, 900)}
SALARY_RANGE = {"mass": (900, 2000), "affluent": (2000, 4500), "premium": (4500, 9000)}
HOUR_WEIGHTS = [1, 1, 1, 1, 1, 2, 4, 8, 10, 10, 10, 11, 12, 11, 10, 10, 11, 12, 12, 11, 9, 6, 4, 2]
PURCHASES_PER_CUSTOMER_DAY, TRANSFERS_PER_CUSTOMER_DAY = 1.2, 0.15
DECLINE_RATE, REFUND_RATE = 0.03, 0.015
REFUND_LOOKBACK_DAYS = 10


def synthetic_lt_iban(rng: Random) -> str:
    """Lithuanian IBAN (20 chars) with valid ISO 13616 mod-97 check digits. L=21, T=29."""
    bban = f"{rng.randint(0, 10**16 - 1):016d}"
    check = 98 - int(bban + "2129" + "00") % 97
    return f"LT{check:02d}{bban}"


def _local_ts(rng: Random, d: date) -> str:
    """Random local Vilnius time on business date d, returned as a UTC timestamp."""
    hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
    local = datetime.combine(d, time(hour, rng.randint(0, 59), rng.randint(0, 59)), tzinfo=VILNIUS)
    return utc_ts(local)


def _day_factor(d: date) -> float:
    """Synthetic volume rhythm: busier Fri/Sat and month-end, quieter Sunday."""
    factor = {4: 1.15, 5: 1.10, 6: 0.80}.get(d.weekday(), 1.0)
    first_of_next_month = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    if (first_of_next_month - d).days <= 3:
        factor *= 1.10
    return factor


def _month_start(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def _txn(tid: str, ts: str, ttype: str, customer_id: str, account_id: str, method: str,
         channel: str, amount: str, currency: str, status: str = "completed", **extra: object) -> dict:
    rec = {"transaction_id": tid, "event_ts": ts, "transaction_type": ttype,
           "customer_id": customer_id, "account_id": account_id, "payment_method": method,
           "channel": channel, "merchant_id": None, "biller_id": None, "bill_reference": None,
           "due_date": None, "counterparty_iban": None, "original_transaction_id": None,
           "amount": amount, "currency": currency, "status": status}
    rec.update(extra)
    return rec


def _purchases(cfg: GenConfig, v: DayView, d: date) -> list[dict]:
    rng = rng_for(cfg.seed, "purchases", d)
    out = []
    for i in range(1, round(len(v.spenders) * PURCHASES_PER_CUSTOMER_DAY * _day_factor(d)) + 1):
        cid = rng.choice(v.spenders)["customer_id"]
        has_card = cid in v.card_acc
        method = rng.choices(["debit_card", "credit_card", "mobile_wallet"],
                             weights=[50, 25 if has_card else 0, 25])[0]
        use_card = method == "credit_card" or (method == "mobile_wallet" and has_card and rng.random() < 0.4)
        account = v.card_acc[cid] if use_card else v.current_acc[cid]
        m = rng.choice(v.merchants)
        currency = CURRENCY_BY_COUNTRY[m["country"]]
        channel = "online" if m["country"] != "LT" else ("pos" if rng.random() < 0.75 else "online")
        lo, hi = AMOUNT_RANGE_EUR[m["category"]]
        amount = money(Decimal(str(rng.uniform(lo, hi))) * FX_BASE.get(currency, Decimal("1")))
        status = "declined" if rng.random() < DECLINE_RATE else "completed"
        out.append(_txn(f"T{d:%Y%m%d}P{i:07d}", _local_ts(rng, d), "purchase", cid, account,
                        method, channel, amount, currency, status, merchant_id=m["merchant_id"]))
    return out


def _refunds(cfg: GenConfig, v: DayView, d: date, n_purchases: int,
             recent: dict[date, list[dict]]) -> list[dict]:
    """Refunds of completed purchases from the previous 1-10 days, as new rows.
    Skips closed accounts; carries the CURRENT customer id (old ids resolved via key changes)."""
    rng = rng_for(cfg.seed, "refunds", d)
    out = []
    for i in range(1, round(n_purchases * REFUND_RATE) + 1):
        candidates = recent.get(d - timedelta(days=rng.randint(1, REFUND_LOOKBACK_DAYS)))
        if not candidates:
            continue
        orig = rng.choice(candidates)
        if orig["account_id"] not in v.active_accounts:
            continue
        amount = (orig["amount"] if rng.random() < 0.7
                  else money(Decimal(orig["amount"]) * Decimal(str(rng.uniform(0.1, 0.9)))))
        out.append(_txn(f"T{d:%Y%m%d}R{i:07d}", _local_ts(rng, d), "refund",
                        resolve_customer(v.alias, orig["customer_id"]), orig["account_id"],
                        orig["payment_method"], orig["channel"], amount, orig["currency"],
                        merchant_id=orig["merchant_id"], original_transaction_id=orig["transaction_id"]))
    return out


def _customer_billers(cfg: GenConfig, origin_id: str) -> list[tuple[str, str, int]]:
    """Each customer pays 1-3 billers monthly; due day 5-28 (stable per original customer id)."""
    rng = rng_for(cfg.seed, "billers", origin_id)
    chosen = rng.sample(ALL_BILLERS, k=rng.randint(1, 3))
    return [(biller_id, bill_type, rng.randint(5, 28)) for biller_id, _, bill_type in chosen]


def _bill_payments(cfg: GenConfig, v: DayView, d: date) -> list[dict]:
    out, n = [], 0
    for c in v.spenders:
        cid = c["customer_id"]
        key = v.origin[cid]
        for biller_id, bill_type, due_day in _customer_billers(cfg, key):
            if biller_id not in v.active_billers:
                continue
            for k in (-1, 0, 1):  # late payment of last month's bill, this month, early for next
                due = _month_start(d, k).replace(day=due_day)
                rng = rng_for(cfg.seed, "billpay", key, biller_id, due)
                offset = rng.choices([rng.randint(-5, -1), 0, rng.randint(1, 10)], weights=[55, 30, 15])[0]
                if due + timedelta(days=offset) != d:
                    continue
                n += 1
                lo, hi = BILL_RANGE[bill_type]
                out.append(_txn(f"T{d:%Y%m%d}B{n:07d}", _local_ts(rng, d), "bill_payment", cid,
                                v.current_acc[cid], "bank_transfer",
                                "mobile_app" if rng.random() < 0.7 else "web", money(rng.uniform(lo, hi)),
                                "EUR", biller_id=biller_id, bill_reference=f"{biller_id}-{cid}-{due:%Y%m}",
                                due_date=due.isoformat()))
    return out


def _transfers_out(cfg: GenConfig, v: DayView, d: date) -> list[dict]:
    """Outgoing SEPA (instant) transfers; can occur any day."""
    rng = rng_for(cfg.seed, "transfers", d)
    out = []
    for i in range(1, round(len(v.spenders) * TRANSFERS_PER_CUSTOMER_DAY * _day_factor(d)) + 1):
        cid = rng.choice(v.spenders)["customer_id"]
        out.append(_txn(f"T{d:%Y%m%d}X{i:07d}", _local_ts(rng, d), "transfer_out", cid,
                        v.current_acc[cid], "bank_transfer", "mobile_app" if rng.random() < 0.75 else "web",
                        money(rng.uniform(10, 500)), "EUR", counterparty_iban=synthetic_lt_iban(rng)))
    return out


def _salaries(cfg: GenConfig, v: DayView, d: date) -> list[dict]:
    """Monthly salary on a fixed day per customer; weekend pay days move to the previous Friday."""
    out, n = [], 0
    for c in v.customers:
        cid = c["customer_id"]
        key = v.origin[cid]
        rng = rng_for(cfg.seed, "salary", key)
        pay_day = rng.randint(1, 28)
        lo, hi = SALARY_RANGE[c["segment"]]
        base = rng.uniform(lo, hi)
        for month_start in (_month_start(d, 0), _month_start(d, 1)):
            scheduled = month_start.replace(day=pay_day)
            while scheduled.weekday() >= 5:
                scheduled -= timedelta(days=1)
            if scheduled != d:
                continue
            n += 1
            r2 = rng_for(cfg.seed, "salary", key, scheduled)
            local = datetime.combine(d, time(r2.randint(6, 8), r2.randint(0, 59), r2.randint(0, 59)),
                                     tzinfo=VILNIUS)
            out.append(_txn(f"T{d:%Y%m%d}S{n:07d}", utc_ts(local), "salary_in", cid, v.current_acc[cid],
                            "bank_transfer", "bank_network", money(base * r2.uniform(0.97, 1.03)), "EUR"))
            break
    return out


def build_transactions(cfg: GenConfig, v: DayView, d: date,
                       recent: dict[date, list[dict]]) -> tuple[list[dict], list[dict]]:
    """Return (all records for day d sorted by event_ts, completed purchases for refund look-back)."""
    purchases = _purchases(cfg, v, d)
    records = (purchases + _refunds(cfg, v, d, len(purchases), recent) + _bill_payments(cfg, v, d)
               + _transfers_out(cfg, v, d) + _salaries(cfg, v, d))
    records.sort(key=lambda r: (r["event_ts"], r["transaction_id"]))
    return records, [p for p in purchases if p["status"] == "completed"]


def is_fx_publication_day(d: date) -> bool:
    return d.weekday() < 5 and (d.month, d.day) not in FX_FIXED_CLOSING_DAYS


def fx_rates_for(cfg: GenConfig, d: date) -> dict[str, Decimal] | None:
    """Synthetic random walk from FX_BASE; None on non-publication days."""
    if not is_fx_publication_day(d):
        return None
    rates = dict(FX_BASE)
    day = cfg.start_date
    while day <= d:
        if is_fx_publication_day(day):
            for cur in rates:
                rates[cur] *= Decimal(str(1 + rng_for(cfg.seed, "fx", day, cur).gauss(0, 0.003)))
        day += timedelta(days=1)
    return {cur: r.quantize(Decimal("0.0001")) for cur, r in sorted(rates.items())}


def fx_records(cfg: GenConfig, d: date) -> list[dict]:
    rates = fx_rates_for(cfg, d)
    if rates is None:
        return []
    return [{"rate_date": d.isoformat(), "base_currency": "EUR", "currency": cur,
             "rate": str(rate), "source": "synthetic"} for cur, rate in rates.items()]
