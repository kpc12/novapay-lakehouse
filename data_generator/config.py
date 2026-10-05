"""Generator configuration. Small defaults keep serverless costs low; scale up later."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class GenConfig:
    seed: int = 42
    start_date: date = date(2026, 9, 1)  # day 0: initial master-data load
    n_customers: int = 2_000
    n_merchants: int = 300
    savings_share: float = 0.40
    credit_card_share: float = 0.45
    joint_account_share: float = 0.08
    output_root: Path = Path("data_generator/output")
