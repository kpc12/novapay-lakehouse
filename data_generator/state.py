"""Day-by-day master-data state and daily change records (Step 1.4a)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from random import Random

from .common import ascii_slug, change_seq, change_time, rng_for
from .config import GenConfig
from .master_data import (BILLERS, FEMALE_FIRST, FEMALE_LAST, LT_CITIES, MALE_FIRST, MALE_LAST, MCCS,
                          NAME_PREFIXES, PHONE_PREFIX, PRODUCTS, build_accounts, build_customers,
                          build_merchants)

# --- Scenario events: fixed, documented test dates inside the Sep-Dec 2026 window ---
KEY_CHANGE_DATE = date(2026, 10, 15)      # core-banking migration re-keys some customers
KEY_CHANGE_COUNT = 3
BILLER_ADDED = ("B-011", "Kaunas Heat (synthetic)", "utility", date(2026, 10, 5))
BILLER_REMOVED = ("B-010", date(2026, 11, 16))
PRODUCT_CHANGE = ("NPX000000009", 7, date(2026, 11, 2))   # risk_level re-rated 6 -> 7
ALL_BILLERS = BILLERS + [BILLER_ADDED[:3]]
# --- Synthetic daily change rates (assumptions, not real statistics) ---
CUSTOMER_UPDATE_RATE = 0.003
NEW_CUSTOMER_RATE = 0.001
ACCOUNT_CLOSE_RATE = 0.0005   # savings and credit-card accounts only
JOINT_REMOVE_RATE = 0.001
MERCHANT_UPDATE_RATE = 0.001
NEW_MERCHANT_RATE = 0.0005
FOREIGN_MERCHANTS = [("PL", "Warszawa"), ("SE", "Stockholm"), ("GB", "London"), ("US", "New York")]
CHANGE_FIELDS = ("op", "change_seq", "change_ts")


def _strip(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in CHANGE_FIELDS}


def resolve_customer(alias: dict[str, str], customer_id: str) -> str:
    """Follow key changes (old id -> new id) to the current customer id."""
    while customer_id in alias:
        customer_id = alias[customer_id]
    return customer_id


@dataclass(frozen=True)
class DayView:
    """Read-only view of the state that transaction generation uses for one day."""
    customers: list[dict]
    spenders: list[dict]               # kyc_status != expired
    current_acc: dict[str, str]        # customer_id -> active current account (primary)
    card_acc: dict[str, str]           # customer_id -> active credit-card account (primary)
    merchants: list[dict]
    active_billers: frozenset[str]
    active_accounts: frozenset[str]
    origin: dict[str, str]             # current customer_id -> original id (stable seed key)
    alias: dict[str, str]              # old customer_id -> new customer_id


@dataclass
class State:
    customers: dict[str, dict]
    accounts: dict[str, dict]
    holders: dict[tuple[str, str], dict]
    merchants: dict[str, dict]
    billers: dict[str, dict]
    products: dict[str, dict]
    origin: dict[str, str]
    alias: dict[str, str]
    next_customer: int
    next_account: int
    next_merchant: int

    @classmethod
    def initial(cls, cfg: GenConfig) -> "State":
        """Day-0 state, identical to what `init` writes (same deterministic builders)."""
        customers = build_customers(cfg)
        accounts, holders = build_accounts(cfg, customers)
        merchants = build_merchants(cfg)
        return cls(
            customers={c["customer_id"]: _strip(c) for c in customers},
            accounts={a["account_id"]: _strip(a) for a in accounts},
            holders={(h["account_id"], h["customer_id"]): _strip(h) for h in holders},
            merchants={m["merchant_id"]: _strip(m) for m in merchants},
            billers={b: {"biller_id": b, "biller_name": n, "bill_type": t} for b, n, t in BILLERS},
            products={i: {"isin": i, "product_name": n, "asset_class": a, "risk_level": r, "currency": "EUR"}
                      for i, n, a, r in PRODUCTS},
            origin={c["customer_id"]: c["customer_id"] for c in customers},
            alias={},
            next_customer=len(customers), next_account=len(accounts), next_merchant=len(merchants),
        )

    def view(self) -> DayView:
        active = frozenset(a for a, rec in self.accounts.items() if rec["status"] == "active")
        current: dict[str, str] = {}
        card: dict[str, str] = {}
        for (account_id, customer_id), holder in sorted(self.holders.items()):
            if holder["role"] != "primary" or account_id not in active:
                continue
            kind = self.accounts[account_id]["account_type"]
            if kind == "current":
                current[customer_id] = account_id
            elif kind == "credit_card":
                card[customer_id] = account_id
        customers = [self.customers[k] for k in sorted(self.customers)]
        return DayView(customers=customers,
                       spenders=[c for c in customers if c["kyc_status"] != "expired"],
                       current_acc=current, card_acc=card,
                       merchants=[self.merchants[k] for k in sorted(self.merchants)],
                       active_billers=frozenset(self.billers), active_accounts=active,
                       origin=dict(self.origin), alias=dict(self.alias))


def _new_customer(rng: Random, n: int, d: date) -> dict:
    """Newly onboarded customer: KYC pending, mass segment, Lithuanian."""
    female = rng.random() < 0.5
    first = rng.choice(FEMALE_FIRST if female else MALE_FIRST)
    last = rng.choice(FEMALE_LAST if female else MALE_LAST)
    return {"customer_id": f"C-{n:06d}", "old_customer_id": None, "first_name": first, "last_name": last,
            "email": f"{ascii_slug(first)}.{ascii_slug(last)}{n}@example.com",
            "phone": f"{PHONE_PREFIX['LT']}{rng.randint(0, 9_999_999):07d}",
            "date_of_birth": (date(1950, 1, 1) + timedelta(days=rng.randint(0, 20_000))).isoformat(),
            "city": rng.choices([c for c, _ in LT_CITIES], weights=[w for _, w in LT_CITIES])[0],
            "country": "LT", "segment": "mass", "kyc_status": "pending", "risk_rating": "medium",
            "customer_since": d.isoformat()}


def _new_merchant(rng: Random, n: int) -> dict:
    mcc, category, _ = rng.choices(MCCS, weights=[w for *_, w in MCCS])[0]
    if rng.random() < 0.08:
        country, city = rng.choice(FOREIGN_MERCHANTS)
    else:
        country = "LT"
        city = rng.choices([c for c, _ in LT_CITIES], weights=[w for _, w in LT_CITIES])[0]
    return {"merchant_id": f"M-{n:05d}", "merchant_name": f"{rng.choice(NAME_PREFIXES)} {category} {n:04d}",
            "mcc": mcc, "category": category, "city": city, "country": country}


def apply_daily_changes(cfg: GenConfig, state: State, d: date) -> dict[str, list[dict]]:
    """Mutate the state for business date d and return change records per entity.
    I/U records carry the full row after the change; D records carry the last known row."""
    out: dict[str, list[dict]] = {"customers": [], "accounts": [], "account_holders": [], "merchants": []}
    rng = rng_for(cfg.seed, "changes", d)

    def emit(entity: str, op: str, record: dict) -> None:
        n = len(out[entity]) + 1
        out[entity].append({"op": op, "change_seq": change_seq(d, n), "change_ts": change_time(d, n), **record})

    # 1. Customer attribute updates (SCD2 input)
    options = {"city": [c for c, _ in LT_CITIES], "segment": ["mass", "affluent", "premium"],
               "risk_rating": ["low", "medium", "high"]}
    for customer_id in sorted(state.customers):
        if rng.random() >= CUSTOMER_UPDATE_RATE:
            continue
        customer = state.customers[customer_id]
        attr = rng.choice(["city", "segment", "risk_rating"])
        if attr == "city" and customer["country"] != "LT":
            continue
        customer[attr] = rng.choice([x for x in options[attr] if x != customer[attr]])
        emit("customers", "U", customer)

    # 2. Key change: core-banking migration assigns new customer ids
    if d == KEY_CHANGE_DATE:
        candidates = sorted(k for k, c in state.customers.items() if c["kyc_status"] == "verified")
        for old_id in rng.sample(candidates, k=min(KEY_CHANGE_COUNT, len(candidates))):
            state.next_customer += 1
            new_id = f"C-{state.next_customer:06d}"
            record = {**state.customers.pop(old_id), "customer_id": new_id, "old_customer_id": old_id}
            emit("customers", "U", record)
            state.customers[new_id] = {**record, "old_customer_id": None}
            state.origin[new_id] = state.origin.pop(old_id)
            state.alias[old_id] = new_id
            for key in sorted(k for k in state.holders if k[1] == old_id):
                holder = state.holders.pop(key)
                emit("account_holders", "D", holder)
                state.holders[(key[0], new_id)] = {**holder, "customer_id": new_id}
                emit("account_holders", "I", state.holders[(key[0], new_id)])

    # 3. New customers, each with a current account and primary holding
    n_new = sum(rng.random() < NEW_CUSTOMER_RATE for _ in range(len(state.customers)))
    for _ in range(n_new):
        state.next_customer += 1
        customer = _new_customer(rng, state.next_customer, d)
        state.customers[customer["customer_id"]] = customer
        state.origin[customer["customer_id"]] = customer["customer_id"]
        emit("customers", "I", customer)
        state.next_account += 1
        account = {"account_id": f"A-{state.next_account:07d}", "account_type": "current", "status": "active",
                   "currency": "EUR", "open_date": d.isoformat(), "credit_limit": None}
        state.accounts[account["account_id"]] = account
        emit("accounts", "I", account)
        holder = {"account_id": account["account_id"], "customer_id": customer["customer_id"], "role": "primary"}
        state.holders[(account["account_id"], customer["customer_id"])] = holder
        emit("account_holders", "I", holder)

    # 4. Closures of savings / credit-card accounts: a status update, not a delete
    for account_id in sorted(state.accounts):
        account = state.accounts[account_id]
        if (account["status"] == "active" and account["account_type"] != "current"
                and rng.random() < ACCOUNT_CLOSE_RATE):
            account["status"] = "closed"
            emit("accounts", "U", account)

    # 5. Joint holders removed: delete record carries the last known row
    for key in sorted(k for k, h in state.holders.items() if h["role"] == "joint"):
        if rng.random() < JOINT_REMOVE_RATE:
            emit("account_holders", "D", state.holders.pop(key))

    # 6. Merchant rebrands / recategorisations, then new merchants
    for merchant_id in sorted(state.merchants):
        if rng.random() >= MERCHANT_UPDATE_RATE:
            continue
        merchant = state.merchants[merchant_id]
        if rng.random() < 0.5:
            merchant["merchant_name"] = f"{rng.choice(NAME_PREFIXES)} {merchant['category']} {merchant_id[2:]}"
        else:
            merchant["mcc"], merchant["category"], _ = rng.choice([x for x in MCCS if x[1] != merchant["category"]])
        emit("merchants", "U", merchant)
    n_new_merchants = sum(rng.random() < NEW_MERCHANT_RATE for _ in range(len(state.merchants)))
    for _ in range(n_new_merchants):
        state.next_merchant += 1
        merchant = _new_merchant(rng, state.next_merchant)
        state.merchants[merchant["merchant_id"]] = merchant
        emit("merchants", "I", merchant)

    # 7. Reference-data events (visible in the daily full snapshots)
    if d == BILLER_ADDED[3]:
        biller_id, name, bill_type, _ = BILLER_ADDED
        state.billers[biller_id] = {"biller_id": biller_id, "biller_name": name, "bill_type": bill_type}
    if d == BILLER_REMOVED[1]:
        state.billers.pop(BILLER_REMOVED[0], None)
    if d == PRODUCT_CHANGE[2]:
        state.products[PRODUCT_CHANGE[0]]["risk_level"] = PRODUCT_CHANGE[1]
    return out
