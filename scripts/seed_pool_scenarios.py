"""Preview or apply resource-pool scenarios through the maintenance service."""

import argparse
import os
import sys
import json
from datetime import date

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.maintenance_cli import add_operator_arguments, cli_errors, maintenance_service


@cli_errors
def main() -> None:
    """Preview the Ressort A pool plan, applying it only with --apply."""
    parser = argparse.ArgumentParser(description=__doc__)
    add_operator_arguments(parser)
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    report = maintenance_service(args).seed_pool_scenarios(
        year=args.year, seed=args.seed, apply=args.apply, replace=args.replace
    )
    sys.stdout.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
