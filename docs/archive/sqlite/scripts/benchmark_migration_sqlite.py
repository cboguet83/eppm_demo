"""Capture the retained SQLite workload, resulting schema, and service timings.

This baseline adapter is archived with SQLite at runtime cutover. Service timings
exclude authentication and browser rendering and cannot satisfy the load gate.
"""

import argparse
from collections.abc import Callable
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import platform
import sqlite3
from statistics import median
from time import perf_counter

from app.infrastructure.database.bulk_seed import seed_database
from app.operator_services import create_planning_service, create_portfolio_service


def measure(operation: Callable[[int], object], repeats: int = 100) -> dict[str, float | int]:
    """Warm one operation and return individual sample statistics in milliseconds."""
    operation(0)
    samples = []
    for index in range(repeats):
        start = perf_counter()
        operation(index)
        samples.append((perf_counter() - start) * 1000)
    return {"samples": repeats, "median_ms": round(median(samples), 3),
            "p95_ms": round(sorted(samples)[int(repeats * 0.95) - 1], 3),
            "max_ms": round(max(samples), 3)}


def capture(database: Path, output: Path, *, reuse: bool = False) -> dict[str, object]:
    """Seed a new isolated fixture or explicitly reuse it, then capture evidence."""
    if database.exists() and not reuse:
        raise ValueError("Baseline database already exists; use --reuse to measure it without reseeding.")
    database.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    seed_seconds = None
    if not database.exists():
        start = perf_counter()
        seed_database(num_projects=10001, min_tasks_per_project=0, max_tasks_per_project=15,
                      random_seed=42, db_path=str(database))
        seed_seconds = round(perf_counter() - start, 3)
    with closing(sqlite3.connect(database)) as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        counts = {name: connection.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
                  for name in names}
        if counts["project"] != 10001:
            raise ValueError("The baseline fixture must contain exactly 10,001 projects.")
        schema = [dict(zip(("type", "name", "table", "sql"), row)) for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )]
        journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        project_ids = [row[0] for row in connection.execute("SELECT id FROM project ORDER BY id LIMIT 100")]
        task_id = connection.execute("SELECT id FROM project_task ORDER BY id LIMIT 1").fetchone()[0]
    (output / "sqlite-schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    portfolio, planning = create_portfolio_service(str(database)), create_planning_service(str(database))
    columns = [{"key": key, "format": "text"} for key in ("project_id", "project_name", "status")]
    report = {
        "baseline_commit": "f564a5b4b49c237902415754c61fe9e77f07f7bc",
        "fixture": {"projects": 10001, "min_tasks": 0, "max_tasks": 15, "random_seed": 42,
                    "pool_scenario_seed": 20260908, "pool_scenario_year": date.today().year},
        "python": platform.python_version(), "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version, "journal_mode": journal,
        "seed_seconds": seed_seconds, "row_counts": counts,
        "measurement_scope": "single operator service calls; excludes OIDC, Streamlit and browser rendering",
        "service_timings": {
            "portfolio_page": measure(lambda index: portfolio.get_page(columns, {}, (index % 100) * 100, include_allocations=False)),
            "visible_tasks": measure(lambda index: planning.get_milestones_for_projects(project_ids[(index % 5) * 20:(index % 5 + 1) * 20])),
            "simple_save": measure(lambda index: planning.update_progress(task_id, index % 101)),
        },
    }
    (output / "sqlite-baseline.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    """Write aggregate evidence only; never print business records or credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true")
    arguments = parser.parse_args()
    report = capture(arguments.database, arguments.output, reuse=arguments.reuse)
    print(json.dumps({key: report[key] for key in ("fixture", "service_timings", "seed_seconds")}, indent=2))


if __name__ == "__main__":
    main()
