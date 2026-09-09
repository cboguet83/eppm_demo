"""Preview, generate, or clear project/task pool allocations through maintenance."""

import argparse
import json
import sys

from app.domain.resources.allocation_generation import AllocationGenerationRequest
from app.operator_services import create_maintenance_service
from app.shared.logging import setup_logging
from scripts.maintenance_cli import cli_errors


@cli_errors
def main() -> None:
    """Expose the same percentage-based generation options as Database Seeding."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("operation", choices=("generate", "clear"))
    parser.add_argument("--db-path")
    parser.add_argument("--apply", action="store_true", help="Back up and apply the requested changes.")
    parser.add_argument("--allocated-pools", type=float, default=80)
    parser.add_argument("--average-allocation", type=float, default=80)
    parser.add_argument("--overallocated-pools", type=float, default=20)
    parser.add_argument("--max-overallocation", type=float, default=50)
    parser.add_argument("--underallocated-pools", type=float, default=50)
    parser.add_argument("--unstaffed-pools", type=float, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    setup_logging()
    service = create_maintenance_service(args.db_path)
    if args.operation == "clear":
        result = {"allocations_removed": service.clear_pool_allocations()} if args.apply else {
            "applied": False, "message": "Use --apply to clear all project/task allocations after a backup.",
        }
    else:
        request = AllocationGenerationRequest(
            args.allocated_pools, args.average_allocation, args.overallocated_pools,
            args.max_overallocation, args.underallocated_pools, args.unstaffed_pools, args.seed,
        )
        result = service.generate_pool_allocations(request, apply=args.apply)
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
