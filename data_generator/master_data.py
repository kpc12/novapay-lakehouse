"""Day-0 master data: customers, accounts, account holders, merchants, billers, products."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .common import ascii_slug, change_seq, change_time, money, rng_for, write_batch
from .config import GenConfig

MALE_FIRST = ["Jonas", "Lukas", "Mantas", "Tomas", "Žydrūnas", "Matas", "Darius", "Paulius"]
FEMALE_FIRST = ["Rūta", "Eglė", "Ieva", "Gabija", "Austėja", "Kotryna", "Vaida", "Aistė"]
MALE_LAST = ["Kazlauskas", "Jankauskas", "Petrauskas", "Stankevičius", "Vasiliauskas",
             "Žukauskas", "Butkus", "Paulauskas", "Urbonas", "Kavaliauskas"]
FEMALE_LAST = ["Kazlauskienė", "Jankauskaitė", "Petrauskienė", "Stankevičiūtė", "Vasiliauskienė",
               "Žukauskaitė", "Butkienė", "Paulauskaitė", "Urbonienė", "Kavaliauskienė"]
LT_CITIES = [("Vilnius", 40), ("Kaunas", 20), ("Klaipėda", 12), ("Šiauliai", 9),
             ("Panevėžys", 8), ("Alytus", 6), ("Marijampolė", 5)]
FOREIGN_CITY = {"LV": "Rīga", "EE": "Tallinn"}
PHONE_PREFIX = {"LT": "+3706", "LV": "+3712", "EE": "+3725"}  # C9

# Real ISO 18245 merchant category codes; merchant names are fictional.
MCCS = [("5411", "Groceries", 30), ("5812", "Restaurants", 15), ("5814", "Fast Food", 10),
        ("5541", "Fuel", 10), ("5912", "Pharmacy", 8), ("5732", "Electronics", 6),
        ("5651", "Clothing", 9), ("4121", "Taxi", 7), ("7832", "Cinema", 5)]
NAME_PREFIXES = ["Baltic", "Nemunas", "Gintaras", "Amber", "Neris", "Vilija"]

BILLERS = [
    ("B-001", "Vilnius Energy (synthetic)", "utility"), ("B-002", "Kaunas Water (synthetic)", "utility"),
    ("B-003", "Baltic Gas (synthetic)", "utility"), ("B-004", "NeroTel Mobile (synthetic)", "telecom"),
    ("B-005", "AmberNet Fibre (synthetic)", "internet"), ("B-006", "Neris Insurance (synthetic)", "insurance"),
    ("B-007", "Gintaras Home Insurance (synthetic)", "insurance"), ("B-008", "City Rentals (synthetic)", "rent"),
    ("B-009", "Vilija Heating (synthetic)", "utility"), ("B-010", "Nemunas TV (synthetic)", "internet"),
]
# risk_level follows the EU PRIIPs summary risk indicator scale (1 = lowest, 7 = highest).
PRODUCTS = [
    ("NPX000000001", "NovaPay Money Market Fund", "money_market", 1),
    ("NPX000000002", "NovaPay Euro Bond Fund", "bond_fund", 2),
    ("NPX000000003", "NovaPay Global Bond Fund", "bond_fund", 3),
    ("NPX000000004", "NovaPay Balanced Fund", "mixed_fund", 3),
    ("NPX000000005", "NovaPay Europe Equity ETF", "etf", 4),
    ("NPX000000006", "NovaPay Global Equity ETF", "etf", 4),
    ("NPX000000007", "NovaPay Baltic Equity Fund", "equity_fund", 5),
    ("NPX000000008", "NovaPay Emerging Markets Fund", "equity_fund", 6),
    ("NPX000000009", "NovaPay Tech Growth ETF", "etf", 6),
    ("NPX000000010", "NovaPay Crypto Tracker (synthetic)", "alternative", 7),
]


def build_customers(cfg: GenConfig) -> list[dict]:
    rng = rng_for(cfg.seed, "customers", "init")
    records = []
    for i in range(1, cfg.n_customers + 1):
        female = rng.random() < 0.5
        first = rng.choice(FEMALE_FIRST if female else MALE_FIRST)
        last = rng.choice(FEMALE_LAST if female else MALE_LAST)
        country = rng.choices(["LT", "LV", "EE"], weights=[92, 5, 3])[0]
        city = (rng.choices([c for c, _ in LT_CITIES], weights=[w for _, w in LT_CITIES])[0]
                if country == "LT" else FOREIGN_CITY[country])
        records.append({
            "op": "I",
            "change_seq": change_seq(cfg.start_date, i),
            "change_ts": change_time(cfg.start_date, i),
            "customer_id": f"C-{i:06d}",
            "old_customer_id": None,
            "first_name": first,
            "last_name": last,
            "email": f"{ascii_slug(first)}.{ascii_slug(last)}{i}@example.com",
            "phone": f"{PHONE_PREFIX[country]}{rng.randint(0, 9_999_999):07d}",
            "date_of_birth": (date(1950, 1, 1) + timedelta(days=rng.randint(0, 20_000))).isoformat(),
            "city": city,
            "country": country,
            "segment": rng.choices(["mass", "affluent", "premium"], weights=[70, 25, 5])[0],
            "kyc_status": rng.choices(["verified", "pending", "expired"], weights=[92, 6, 2])[0],
            "risk_rating": rng.choices(["low", "medium", "high"], weights=[70, 25, 5])[0],
            "customer_since": (cfg.start_date - timedelta(days=rng.randint(30, 3_000))).isoformat(),  # C8
        })
    return records


def build_accounts(cfg: GenConfig, customers: list[dict]) -> tuple[list[dict], list[dict]]:
    rng = rng_for(cfg.seed, "accounts", "init")
    accounts: list[dict] = []
    holders: list[dict] = []
    verified_ids = [c["customer_id"] for c in customers if c["kyc_status"] == "verified"]

    def add_holder(account_id: str, customer_id: str, role: str) -> None:
        n = len(holders) + 1
        holders.append({"op": "I", "change_seq": change_seq(cfg.start_date, n),
                        "change_ts": change_time(cfg.start_date, n),
                        "account_id": account_id, "customer_id": customer_id, "role": role})

    def add_account(customer: dict, account_type: str, open_date: date) -> str:
        n = len(accounts) + 1
        account_id = f"A-{n:07d}"
        accounts.append({
            "op": "I", "change_seq": change_seq(cfg.start_date, n),
            "change_ts": change_time(cfg.start_date, n),
            "account_id": account_id, "account_type": account_type, "status": "active",
            "currency": "EUR", "open_date": open_date.isoformat(),
            "credit_limit": money(rng.randrange(1_000, 10_001, 500)) if account_type == "credit_card" else None,
        })
        add_holder(account_id, customer["customer_id"], "primary")
        return account_id

    def later_open_date(customer: dict) -> date:
        """C10: between customer_since and the day before the start date."""
        since = date.fromisoformat(customer["customer_since"])
        return since + timedelta(days=rng.randint(0, (cfg.start_date - since).days - 1))

    for c in customers:
        current_id = add_account(c, "current", date.fromisoformat(c["customer_since"]))
        if verified_ids and rng.random() < cfg.joint_account_share:
            partner = rng.choice(verified_ids)          # C10: joint holders are KYC-verified
            if partner != c["customer_id"]:             # and differ from the primary holder
                add_holder(current_id, partner, "joint")
        if rng.random() < cfg.savings_share:
            add_account(c, "savings", later_open_date(c))
        if c["kyc_status"] == "verified" and rng.random() < cfg.credit_card_share:
            add_account(c, "credit_card", later_open_date(c))
    return accounts, holders


def build_merchants(cfg: GenConfig) -> list[dict]:
    rng = rng_for(cfg.seed, "merchants", "init")
    records = []
    for i in range(1, cfg.n_merchants + 1):
        mcc, category, _ = rng.choices(MCCS, weights=[w for *_, w in MCCS])[0]
        records.append({
            "op": "I", "change_seq": change_seq(cfg.start_date, i),
            "change_ts": change_time(cfg.start_date, i),
            "merchant_id": f"M-{i:05d}",
            "merchant_name": f"{rng.choice(NAME_PREFIXES)} {category} {i:04d}",
            "mcc": mcc, "category": category,
            "city": rng.choices([c for c, _ in LT_CITIES], weights=[w for _, w in LT_CITIES])[0],
            "country": "LT",
        })
    return records


def generate_initial(cfg: GenConfig) -> list[Path]:
    """Write the day-0 (initial full load) master data. Returns the folders written."""
    d, root = cfg.start_date, cfg.output_root
    customers = build_customers(cfg)
    accounts, holders = build_accounts(cfg, customers)
    billers = [{"biller_id": b, "biller_name": n, "bill_type": t} for b, n, t in BILLERS]
    products = [{"isin": i, "product_name": n, "asset_class": a, "risk_level": r, "currency": "EUR"}
                for i, n, a, r in PRODUCTS]
    return [
        write_batch(root, "core_banking", "customers", d, customers),
        write_batch(root, "core_banking", "accounts", d, accounts),
        write_batch(root, "core_banking", "account_holders", d, holders),
        write_batch(root, "acquirer", "merchants", d, build_merchants(cfg)),
        write_batch(root, "reference", "billers", d, billers),
        write_batch(root, "reference", "invest_products", d, products),
    ]
