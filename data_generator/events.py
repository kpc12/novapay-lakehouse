"""KYC checks, investment holdings, support cases and credit bureau scores (Step 1.4b)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from random import Random

from .common import change_seq, money, rng_for, utc_ts
from .config import GenConfig
from .state import DayView, State, resolve_customer
from .transactions import VILNIUS, is_fx_publication_day

# --- Synthetic assumptions (invented; not real statistics or regulatory rules) ---
KYC_PENDING_CHECK_RATE = 0.20       # share of pending customers checked per day
KYC_PERIODIC_REVIEW_RATE = 0.0005   # share of verified customers re-reviewed per day
KYC_REVERIFY_RATE = 0.05            # share of expired customers re-verified per day
INVESTOR_SHARE = {"mass": 0.10, "affluent": 0.60, "premium": 0.90}
MAX_PRODUCT_RISK = {"low": 3, "medium": 5, "high": 7}   # illustrative suitability rule
TRADE_RATE = 0.01
CASE_BASE_RATE = 0.0015
CASE_AFTER_DECLINE_RATE = 0.15
CASE_REASONS = ["card_issue", "login_problem", "fee_question", "transfer_status"]
CASE_CHANNELS = [("chat", 60), ("phone", 25), ("email", 15)]
BASE_SCORE = {"low": 760, "medium": 620, "high": 470}
BAND_LIMITS = [(800, "A"), (650, "B"), (500, "C"), (350, "D")]   # below 350 = "E"
UNITS = Decimal("0.0001")


def is_business_day(d: date) -> bool:
    """TARGET business day: the calendar used by the custodian and the credit bureau."""
    return is_fx_publication_day(d)


def is_first_business_day_of_month(d: date) -> bool:
    return is_business_day(d) and not any(is_business_day(d.replace(day=k)) for k in range(1, d.day))


def _local(rng: Random, d: date, first_hour: int, last_hour: int) -> str:
    """Random local Vilnius time on date d between the given hours, as a UTC timestamp."""
    local = datetime.combine(d, time(rng.randint(first_hour, last_hour), rng.randint(0, 59),
                                     rng.randint(0, 59)), tzinfo=VILNIUS)
    return utc_ts(local)


# ---------------------------------------------------------------- KYC checks
def run_kyc_checks(cfg: GenConfig, state: State, d: date) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Run the day's KYC checks. Returns (check events, [(customer row after change, check_ts)]).
    pending -> verified on pass; verified -> expired on failed periodic review;
    expired -> verified on passed re-verification."""
    rng = rng_for(cfg.seed, "kyc", d)
    checks: list[dict] = []
    changed: list[tuple[dict, str]] = []
    for customer_id in sorted(state.customers):
        customer = state.customers[customer_id]
        status = customer["kyc_status"]
        if status == "pending":
            if rng.random() >= KYC_PENDING_CHECK_RATE:
                continue
            check_type = "identity_document"
            result = rng.choices(["pass", "fail", "review"], weights=[85, 10, 5])[0]
            new_status = "verified" if result == "pass" else "pending"
        elif status == "verified":
            if rng.random() >= KYC_PERIODIC_REVIEW_RATE:
                continue
            check_type = "periodic_review"
            result = rng.choices(["pass", "fail"], weights=[90, 10])[0]
            new_status = "verified" if result == "pass" else "expired"
        else:
            if rng.random() >= KYC_REVERIFY_RATE:
                continue
            check_type = "re_verification"
            result = rng.choices(["pass", "fail"], weights=[70, 30])[0]
            new_status = "verified" if result == "pass" else "expired"
        ts = _local(rng, d, 8, 17)
        checks.append({"kyc_check_id": f"K{d:%Y%m%d}{len(checks) + 1:06d}", "check_ts": ts,
                       "customer_id": customer_id, "check_type": check_type, "result": result,
                       "provider": "synthetic"})
        if new_status != status:
            customer["kyc_status"] = new_status
            changed.append(({**customer}, ts))
    checks.sort(key=lambda c: (c["check_ts"], c["kyc_check_id"]))
    return checks, changed


# ---------------------------------------------------------------- Holdings
@dataclass
class HoldingsBook:
    prices: dict[str, Decimal]
    positions: dict[tuple[str, str], Decimal]   # (original customer id, isin) -> units

    @classmethod
    def initial(cls, cfg: GenConfig, state: State) -> "HoldingsBook":
        rng = rng_for(cfg.seed, "holdings", "init")
        prices = {isin: Decimal(str(round(rng.uniform(10, 100), 4))) for isin in sorted(state.products)}
        positions: dict[tuple[str, str], Decimal] = {}
        for customer_id in sorted(state.customers):
            customer = state.customers[customer_id]
            origin = state.origin[customer_id]
            r = rng_for(cfg.seed, "investor", origin)
            if r.random() >= INVESTOR_SHARE[customer["segment"]]:
                continue
            limit = MAX_PRODUCT_RISK[customer["risk_rating"]]
            eligible = sorted(i for i, p in state.products.items() if p["risk_level"] <= limit)
            for isin in r.sample(eligible, k=min(len(eligible), r.randint(1, 4))):
                positions[(origin, isin)] = Decimal(str(round(r.uniform(5, 500), 4)))
        return cls(prices, positions)

    def step(self, cfg: GenConfig, d: date, state: State) -> list[dict]:
        """Business day: move prices, apply occasional trades, return end-of-day positions."""
        for isin in sorted(self.prices):
            vol = Decimal("0.002") * state.products[isin]["risk_level"]
            change = Decimal(str(rng_for(cfg.seed, "price", d, isin).gauss(0, 1))) * vol
            self.prices[isin] = max(Decimal("0.01"), self.prices[isin] * (1 + change)).quantize(UNITS)
        rng = rng_for(cfg.seed, "trades", d)
        for key in sorted(self.positions):
            if rng.random() < TRADE_RATE:
                factor = Decimal(str(round(rng.uniform(0.5, 1.5), 4)))
                self.positions[key] = (self.positions[key] * factor).quantize(UNITS)
        current_id = {origin: cid for cid, origin in state.origin.items()}
        records = []
        for origin, isin in sorted(self.positions):
            customer_id = current_id.get(origin)
            if customer_id is None:
                continue
            units, price = self.positions[(origin, isin)], self.prices[isin]
            records.append({"business_date": d.isoformat(), "customer_id": customer_id, "isin": isin,
                            "units": str(units), "price": str(price),
                            "market_value": money(units * price), "currency": "EUR"})
        return records


# ---------------------------------------------------------------- Support cases
@dataclass
class CaseBook:
    open_cases: dict[str, dict] = field(default_factory=dict)
    schedule: dict[date, list[tuple[str, str]]] = field(default_factory=dict)

    def step(self, cfg: GenConfig, d: date, v: DayView, declined_customers: set[str]) -> list[dict]:
        """Progress scheduled cases, then open new ones. Returns change records (I/U)."""
        out: list[dict] = []

        def emit(op: str, row: dict, ts: str) -> None:
            out.append({"op": op, "change_seq": change_seq(d, len(out) + 1), "change_ts": ts, **row})

        for case_id, status in self.schedule.pop(d, []):
            row = self.open_cases[case_id]
            ts = _local(rng_for(cfg.seed, "case_event", case_id, status), d, 8, 20)
            row["first_response_ts" if status == "in_progress" else "resolved_ts"] = ts
            row["status"] = status
            row["customer_id"] = resolve_customer(v.alias, row["customer_id"])
            emit("U", row, ts)
            if status == "resolved":
                del self.open_cases[case_id]

        rng = rng_for(cfg.seed, "cases", d)
        n_open = 0
        for customer in v.customers:
            customer_id = customer["customer_id"]
            declined = customer_id in declined_customers
            if rng.random() >= (CASE_AFTER_DECLINE_RATE if declined else CASE_BASE_RATE):
                continue
            n_open += 1
            case_id = f"CS{d:%Y%m%d}{n_open:05d}"
            reason = "declined_payment" if declined else rng.choice(CASE_REASONS)
            channel = rng.choices([ch for ch, _ in CASE_CHANNELS], weights=[w for _, w in CASE_CHANNELS])[0]
            opened = _local(rng, d, 8, 20)
            row = {"case_id": case_id, "customer_id": customer_id, "channel": channel, "reason": reason,
                   "status": "opened", "opened_ts": opened, "first_response_ts": None, "resolved_ts": None}
            self.open_cases[case_id] = row
            emit("I", row, opened)
            respond_day = d + timedelta(days=rng.randint(1, 2))
            resolve_day = respond_day + timedelta(days=rng.randint(1, 5))
            self.schedule.setdefault(respond_day, []).append((case_id, "in_progress"))
            self.schedule.setdefault(resolve_day, []).append((case_id, "resolved"))
        return out


# ---------------------------------------------------------------- Credit bureau
@dataclass
class Bureau:
    late_days: dict[tuple[str, str], int] = field(default_factory=dict)   # (origin, yyyy-mm) -> max

    def record_bill_payments(self, records: list[dict], v: DayView, d: date) -> None:
        """Track the maximum days late per customer for bill payments paid in each month."""
        for r in records:
            if r["transaction_type"] != "bill_payment":
                continue
            late = (d - date.fromisoformat(r["due_date"])).days
            if late > 0:
                key = (v.origin[r["customer_id"]], f"{d:%Y-%m}")
                self.late_days[key] = max(self.late_days.get(key, 0), late)

    def report(self, cfg: GenConfig, d: date, v: DayView) -> list[dict]:
        """Monthly file for the previous month, delivered on the first business day."""
        report_month = f"{d.replace(day=1) - timedelta(days=1):%Y-%m}"
        out = []
        for customer in v.customers:
            customer_id = customer["customer_id"]
            origin = v.origin[customer_id]
            rng = rng_for(cfg.seed, "bureau", origin, report_month)
            base = BASE_SCORE[customer["risk_rating"]] + rng_for(cfg.seed, "bureau", origin).randint(-60, 60)
            dpd = self.late_days.get((origin, report_month), 0)
            score = max(1, min(999, base + rng.randint(-15, 15) - 3 * dpd))
            band = next((b for limit, b in BAND_LIMITS if score >= limit), "E")
            out.append({"report_month": report_month, "customer_id": customer_id, "score": score,
                        "risk_band": band, "open_credit_lines": rng.randint(0, 4),
                        "days_past_due_max": dpd, "bureau": "synthetic"})
        return out
