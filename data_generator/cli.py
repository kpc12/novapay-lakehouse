"""Command line entry point:
python -m data_generator.cli <init|daily|chaos|upload|deliver-late|redeliver>."""
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
from .upload import (LANDING_VOLUME, MANIFEST, UploadError, VolumeTarget, deliver_late, find_batches,
                     redeliver, upload)

DELIVERY_COMMANDS = ("upload", "deliver-late", "redeliver")


def _common_args(parser: argparse.ArgumentParser, defaults: GenConfig) -> None:
    parser.add_argument("--out", type=Path, default=defaults.output_root)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--customers", type=int, default=defaults.n_customers)


def _delivery_args(parser: argparse.ArgumentParser, defaults: GenConfig) -> None:
    parser.add_argument("--out", type=Path, default=defaults.output_root)
    parser.add_argument("--profile", default="novapay", help="Databricks CLI profile (OAuth)")
    parser.add_argument("--volume", default=LANDING_VOLUME)
    parser.add_argument("--dry-run", action="store_true", help="show what would be delivered; no network")


def _run_delivery(args: argparse.Namespace) -> None:
    base = {"upload": args.out, "deliver-late": args.out / "_late",
            "redeliver": args.out / "_chaos" / "redelivery"}[args.command]
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    batches = find_batches(base, start, end)
    if args.dry_run:
        files = sum(2 if args.command == "redeliver" else
                    1 + sum(1 for p in b.folder.iterdir() if p.is_file() and p.name != MANIFEST)
                    for b in batches)
        print(f"{args.command}: {len(batches)} batches, {files} files (dry run; nothing uploaded)")
        for b in batches[:5]:
            print(f"  {b.rel_dir}")
        return
    target = VolumeTarget(args.profile)
    try:
        if args.command == "upload":
            result = upload(target, args.out, args.volume, start, end)
        elif args.command == "deliver-late":
            result = deliver_late(target, args.out, args.volume)
        else:
            result = redeliver(target, args.out, args.volume)
    except UploadError as exc:
        sys.exit(f"{args.command} refused: {exc}")
    print(f"{args.command}: {result.batches} batches delivered, {result.files} files uploaded, "
          f"{result.skipped_batches} batches already delivered")


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
    up = sub.add_parser("upload", help="deliver batches to the landing volume (data first, manifest last)")
    _delivery_args(up, defaults)
    up.add_argument("--start", type=date.fromisoformat, default=None)
    up.add_argument("--end", type=date.fromisoformat, default=None)
    late = sub.add_parser("deliver-late", help="deliver batches held back in _late/ (S10)")
    _delivery_args(late, defaults)
    red = sub.add_parser("redeliver", help="redeliver the truncated batch as a new part file (S09)")
    _delivery_args(red, defaults)
    args = parser.parse_args(argv)

    if args.command in DELIVERY_COMMANDS:
        _run_delivery(args)
        return
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
