"""Command line entry point: python -m data_generator.cli <command>."""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .config import GenConfig
from .master_data import generate_initial


def main(argv: list[str] | None = None) -> None:
    defaults = GenConfig()
    parser = argparse.ArgumentParser(prog="novapay-gen", description="NovaPay synthetic data generator")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="write day-0 master data (initial full load)")
    init.add_argument("--out", type=Path, default=defaults.output_root)
    init.add_argument("--seed", type=int, default=defaults.seed)
    init.add_argument("--customers", type=int, default=defaults.n_customers)
    args = parser.parse_args(argv)

    cfg = replace(defaults, output_root=args.out, seed=args.seed, n_customers=args.customers)
    if args.command == "init":
        for path in generate_initial(cfg):
            print(f"wrote {path}")


if __name__ == "__main__":
    main()
