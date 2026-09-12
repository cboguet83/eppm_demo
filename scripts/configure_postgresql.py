"""Generate ignored local PostgreSQL credentials without changing existing files."""

import argparse
import os
from pathlib import Path
from secrets import token_hex, token_urlsafe


def configure(destination: Path) -> None:
    """Create an exclusive local configuration file with distinct role secrets.

    Args:
        destination: An ignored local environment file, never a tracked example.
    """
    if destination.suffix != ".env" or ".local" not in destination.parts:
        raise ValueError("Use an environment file inside the ignored .local directory.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    operator_password, runtime_password = token_urlsafe(36), token_urlsafe(36)
    values = {
        "POSTGRES_PASSWORD": operator_password,
        "EPPM_RUNTIME_PASSWORD": runtime_password,
        "DATABASE_CONTEXT_KEY": token_hex(32),
        "DATABASE_URL": f"postgresql://eppm_app:{runtime_password}@postgres:5432/eppm",
        "DATABASE_OPERATOR_URL": f"postgresql://eppm_operator:{operator_password}@postgres:5432/eppm",
        "POSTGRES_TEST_ADMIN_URL": f"postgresql://eppm_operator:{operator_password}@127.0.0.1:15432/eppm",
        "POSTGRES_TEST_RUNTIME_URL": f"postgresql://eppm_app:{runtime_password}@127.0.0.1:15432/eppm",
        "DATABASE_POOL_MIN": "2",
        "DATABASE_POOL_MAX": "20",
        "DATABASE_ACQUIRE_TIMEOUT": "5",
        "DATABASE_STATEMENT_TIMEOUT": "10",
    }
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.writelines(f"{name}={value}\n" for name, value in values.items())


def main() -> None:
    """Generate configuration explicitly; refuse to overwrite existing secrets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/postgresql.env"))
    arguments = parser.parse_args()
    try:
        configure(arguments.output)
    except (OSError, ValueError):
        parser.exit(1, "Configuration could not be created; use a new .local/*.env file.\n")


if __name__ == "__main__":
    main()
