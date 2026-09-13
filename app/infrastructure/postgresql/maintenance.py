"""Explicit native operator entry points sharing pre-operation archive policy."""

from datetime import date
from dataclasses import replace
from secrets import randbits

from app.application.ports.maintenance import DatabaseCounts, PoolSeedReport, SeedRequest
from app.application.services.maintenance import validate_seed_request
from app.infrastructure.postgresql.backup import PostgresBackup
from app.infrastructure.postgresql.bulk_seed import generate_projects
from app.infrastructure.postgresql.maintenance_write import backed_up_write
from app.infrastructure.postgresql.pool import OperatorDatabase
from app.infrastructure.postgresql.pool_scenarios import apply_pool_scenarios, prepare_pool_scenarios
from app.infrastructure.postgresql.reset import flush_projects
from app.infrastructure.postgresql.seed_catalog import can_install_demo
from app.infrastructure.postgresql.seed_plan import source_fingerprint
from app.infrastructure.postgresql.seeder import install_default_data


def seed_defaults(database: OperatorDatabase, backup: PostgresBackup, *, force: bool = False,
                  include_projects: bool = True, year: int | None = None) -> bool:
    """Back up once before installing references and the optional full demo."""
    current_year = date.today().year if year is None else year
    if type(current_year) is not int or not 1 <= current_year <= 9999:
        raise ValueError('Invalid scenario year.')
    fingerprint, needed = database.run(lambda connection: (source_fingerprint(connection),
        force or can_install_demo(connection) or not connection.execute(
            "SELECT 1 FROM eppm.operator_seed_state WHERE catalog='reference'").fetchone()))
    if not needed:
        return False
    return backed_up_write(database, backup, reason='seed', fingerprint=fingerprint,
        operation=lambda connection: install_default_data(connection, force=force, include_projects=include_projects, year=current_year))


def reset_database(database: OperatorDatabase, backup: PostgresBackup, *, flush_all: bool = False) -> dict[str, int]:
    """Back up and remove requested business records in one native transaction."""
    return backed_up_write(database, backup, reason='reset', fingerprint=database.run(source_fingerprint),
        operation=lambda connection: flush_projects(connection, flush_all=flush_all))


def seed_projects(database: OperatorDatabase, backup: PostgresBackup, request: SeedRequest) -> dict[str, int]:
    """Freeze options once and run the full project generator under one archive."""
    validate_seed_request(request)
    frozen = replace(request, random_seed=randbits(128)) if request.random_seed is None else request
    year = date.today().year
    return backed_up_write(database, backup, reason='seed-projects', fingerprint=database.run(source_fingerprint),
        operation=lambda connection: generate_projects(connection, frozen, year=year))


def counts(database: OperatorDatabase) -> DatabaseCounts:
    """Read all maintenance counts in one consistent native snapshot."""
    row = database.run(lambda connection: connection.execute('''SELECT
        (SELECT count(*) FROM eppm.project), (SELECT count(*) FROM eppm.project_task),
        (SELECT count(*) FROM eppm.task_dependencies), (SELECT count(*) FROM eppm.project_type),
        (SELECT count(*) FROM eppm.project_property_value), (SELECT count(*) FROM eppm.resource_pool)''').fetchone())
    return DatabaseCounts(projects=row[0], tasks=row[1], dependencies=row[2], project_types=row[3], property_values=row[4], pools=row[5])


def clear_pool_allocations(database: OperatorDatabase, backup: PostgresBackup) -> int:
    """Archive and clear demand while retaining pools and employee membership."""
    return backed_up_write(database, backup, reason='clear-allocations', fingerprint=database.run(source_fingerprint),
        operation=lambda connection: connection.execute('DELETE FROM eppm.resource_pool_assignment').rowcount)


def seed_pool_scenarios(database: OperatorDatabase, backup: PostgresBackup, *, year: int | None = None,
                        seed: int = 20260908, apply: bool = False) -> PoolSeedReport:
    """Preview without writes or archive and apply a frozen additive plan once."""
    current_year = date.today().year if year is None else year
    plan = database.run(lambda connection: prepare_pool_scenarios(connection, year=current_year, seed=seed))
    if not apply or not plan.inserts:
        return plan.report()
    return backed_up_write(database, backup, reason='seed-pools', fingerprint=plan.fingerprint,
        operation=lambda connection: apply_pool_scenarios(connection, plan))
