"""Preview or apply resource-pool scenarios through the maintenance service."""

import argparse
import os
import sys
import json
from datetime import date

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import create_maintenance_service
from scripts.maintenance_cli import cli_errors


@cli_errors
def main() -> None:
    """Preview an additive pool plan, applying it only with --apply."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("DB_NAME", "data/ppm_mock.db"))
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = create_maintenance_service(args.db).seed_pool_scenarios(
        year=args.year, seed=args.seed, apply=args.apply
    )
    sys.stdout.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
