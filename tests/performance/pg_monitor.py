"""Sample only aggregate PostgreSQL timings and wait categories in a test cluster."""

import json
import os
from pathlib import Path
from time import monotonic, sleep, time

import psycopg


def main() -> None:
    """Use separate operator authority to observe, without storing SQL or actors."""
    directory = Path("/app/data")
    with psycopg.connect(os.environ["DATABASE_OPERATOR_URL"], autocommit=True,
                         application_name="eppm-load-monitor",
                         options="-c statement_timeout=5000") as connection, \
            (directory / "postgresql-timings.jsonl").open("w", encoding="utf-8", buffering=1) as target:
        last = monotonic()
        while not (directory / "monitor.stop").exists():
            waits = dict(connection.execute(
                "SELECT coalesce(wait_event_type,'CPU'),count(*) FROM pg_stat_activity "
                "WHERE application_name='eppm-runtime' AND state='active' GROUP BY 1").fetchall())
            totals = connection.execute(
                "SELECT coalesce(sum(calls),0),coalesce(sum(total_exec_time),0),"
                "coalesce(sum(shared_blks_hit),0),coalesce(sum(shared_blks_read),0) "
                "FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database()) "
                "AND toplevel AND userid=(SELECT oid FROM pg_roles WHERE rolname='eppm_app')").fetchone()
            now = monotonic()
            target.write(json.dumps({"epoch": time(), "sample_interval_seconds": now-last,
                                     "active_wait_categories": waits,
                                     "cumulative": dict(zip(("calls", "server_exec_ms", "shared_hits", "shared_reads"), map(float, totals)))}) + "\n")
            last = now
            sleep(.25)


if __name__ == "__main__":
    main()
