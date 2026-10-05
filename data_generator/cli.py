"""Command line entry point: python -m data_generator.cli <init|daily|chaos>."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from .chaos import ChaosError, apply_chaos
from .config import GenConfig
from .daily import run_daily
from .master_data import generate_initial


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
    daily = sub.add_parser("daily", help="simulate day by day and write daily files")
    _common_args(daily, defaults)
    daily.add_argument("--start", type=date.fromisoformat, default=defaults.start_date)
    daily.add_argument("--end", type=date.fromisoformat, required=True)
    chaos = sub.add_parser("chaos", help="inject documented production faults (once) and log them")
    _common_args(chaos, defaults)
    args = parser.parse_args(argv)

    cfg = replace(defaults, output_root=args.out, seed=args.seed, n_customers=args.customers)
    if args.command == "chaos":
        try:
            log = apply_chaos(cfg)
        except ChaosError as exc:
            sys.exit(f"chaos refused: {exc}")
        for entry in log:
            print(f"{entry['code']:<30} {entry['source']}/{entry['entity']:<14} "
                  f"{entry['business_date']}  affected={entry['affected']}")
        return
    if args.command == "init":
        paths = generate_initial(cfg)
    else:
        if args.start < cfg.start_date:
            parser.error(f"--start cannot be before the master-data start date {cfg.start_date}")
        if args.end < args.start:
            parser.error("--end must be on or after --start")
        paths = run_daily(cfg, args.start, args.end)
    for p in paths:
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
