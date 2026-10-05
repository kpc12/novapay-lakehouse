"""Command line entry point: python -m data_generator.cli <command>."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path

from .config import GenConfig
from .master_data import generate_initial
from .transactions import generate_range


def _common_args(parser: argparse.ArgumentParser, defaults: GenConfig) -> None:
    parser.add_argument("--out", type=Path, default=defaults.output_root)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--customers", type=int, default=defaults.n_customers)


def main(argv: list[str] | None = None) -> None:
    defaults = GenConfig()
    parser = argparse.ArgumentParser(prog="novapay-gen", description="NovaPay synthetic data generator")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="write day-0 master data (initial full load)")
    _common_args(init, defaults)
    daily = sub.add_parser("daily", help="write daily transactions and FX rates for a date range")
    _common_args(daily, defaults)
    daily.add_argument("--start", type=date.fromisoformat, default=defaults.start_date)
    daily.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)

    cfg = replace(defaults, output_root=args.out, seed=args.seed, n_customers=args.customers)
    if args.command == "init":
        paths = generate_initial(cfg)
    else:
        if args.start < cfg.start_date:
            parser.error(f"--start cannot be before the master-data start date {cfg.start_date}")
        if args.end < args.start:
            parser.error("--end must be on or after --start")
        paths = generate_range(cfg, args.start, args.end)
    for p in paths:
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
