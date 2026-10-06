"""Landing sources and their Bronze tables: the single source of truth for ingestion."""
from __future__ import annotations

from dataclasses import dataclass

# Matches .../yyyy/mm/dd/<file>; used to derive _batch_date from the landing path.
BATCH_DATE_PATTERN = r"/(\d{4})/(\d{2})/(\d{2})/[^/]+$"


@dataclass(frozen=True)
class SourceEntity:
    source: str
    entity: str
    cadence: str    # daily | business_day | monthly (informational; used by orchestration later)

    @property
    def landing_subpath(self) -> str:
        return f"{self.source}/{self.entity}"

    @property
    def bronze_table(self) -> str:
        return f"bronze.{self.entity}"


SOURCE_ENTITIES = [
    SourceEntity("core_banking", "customers", "daily"),
    SourceEntity("core_banking", "accounts", "daily"),
    SourceEntity("core_banking", "account_holders", "daily"),
    SourceEntity("acquirer", "merchants", "daily"),
    SourceEntity("reference", "billers", "daily"),
    SourceEntity("reference", "invest_products", "daily"),
    SourceEntity("reference", "fx_rates", "business_day"),
    SourceEntity("kyc_vendor", "kyc_checks", "daily"),
    SourceEntity("payments", "transactions", "daily"),
    SourceEntity("crm", "support_cases", "daily"),
    SourceEntity("custodian", "holdings", "business_day"),
    SourceEntity("credit_bureau", "credit_scores", "monthly"),
]
