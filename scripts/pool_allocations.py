"""Preview, generate, or clear project/task pool allocations through maintenance."""

import argparse
import json
import sys

from app.domain.resources.allocation_generation import AllocationGenerationRequest
from app.shared.logging import setup_logging
from scripts.maintenance_cli import add_operator_arguments, cli_errors, maintenance_service


@cli_errors
def main() -> None:
    """Expose the same percentage-based generation options as Database Seeding."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("operation", choices=("generate", "clear"))
    add_operator_arguments(parser)
    parser.add_argument("--expected-fingerprint", help="Source fingerprint from a reviewed preview.")
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
    service = maintenance_service(args)
    if args.operation == "clear":
        result = {"allocations_removed": service.clear_pool_allocations()} if args.apply else {
            "applied": False, "message": "Use --apply to clear all project/task allocations after a backup.",
        }
    else:
        request = AllocationGenerationRequest(
            args.allocated_pools, args.average_allocation, args.overallocated_pools,
            args.max_overallocation, args.underallocated_pools, args.unstaffed_pools, args.seed,
        )
        result = service.generate_pool_allocations(request, apply=args.apply, expected_fingerprint=args.expected_fingerprint)
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
