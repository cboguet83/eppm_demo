"""Provision ignored, randomly generated credentials for the local Keycloak realm."""

from argparse import ArgumentParser
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit


def local_environment(origin: str = "http://localhost:8501", *, provider_port: int = 8080) -> dict[str, str]:
    """Generate independent local-only secrets without static demo passwords."""
    from app.shared.config.authentication import AuthenticationConfig

    parsed = urlsplit(origin)
    if parsed.scheme != "http" or parsed.hostname != "localhost":
        raise ValueError("Local Compose uses an http://localhost application origin.")
    if type(provider_port) is not int or not 1024 <= provider_port <= 65535:
        raise ValueError("The local provider port must be between 1024 and 65535.")
    if parsed.port is None or not 1024 <= parsed.port <= 65535 or parsed.port == provider_port:
        raise ValueError("Choose distinct application and provider ports between 1024 and 65535.")
    values = {"APP_ENV": "development", "APP_ORIGIN": origin,
              "OIDC_ISSUER": f"http://localhost:{provider_port}/realms/eppm",
              "OIDC_LOCAL_PORT": str(provider_port), "APP_LOCAL_PORT": str(parsed.port),
              "OIDC_CLIENT_ID": "eppm", "OIDC_ALLOW_LOCAL_HTTP": "true",
              "DB_NAME": "data/ppm_mock.db"}
    for name in ("APP_COOKIE_SECRET", "OIDC_CLIENT_SECRET", "KEYCLOAK_ADMIN_PASSWORD",
                 "KEYCLOAK_ALEX_PASSWORD", "KEYCLOAK_SAM_PASSWORD", "KEYCLOAK_ROBIN_PASSWORD"):
        values[name] = secrets.token_urlsafe(48)
    AuthenticationConfig.from_environment(values)
    return values


def provision(destination: Path, origin: str = "http://localhost:8501", *, provider_port: int = 8080) -> None:
    """Create a new environment file without reading or overwriting existing secrets."""
    values = local_environment(origin, provider_port=provider_port)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write("# Generated local development credentials. Keep this file private and Git-ignored.\n")
        output.writelines(f"{name}={value}\n" for name, value in values.items())


def run(argv: list[str] | None = None) -> int:
    """Prepare local configuration and print only its location, never credentials."""
    parser = ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--origin", default="http://localhost:8501")
    parser.add_argument("--provider-port", type=int, default=8080)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / ".local" / "oidc.env")
    args = parser.parse_args(argv)
    destination = args.output
    try:
        provision(destination, args.origin, provider_port=args.provider_port)
    except FileExistsError:
        sys.stderr.write("Local OIDC configuration already exists; it was not overwritten.\n")
        return 1
    except (OSError, ValueError):
        sys.stderr.write("Unable to create local OIDC configuration. Verify the origin and directory permissions.\n")
        return 1
    sys.stdout.write(f"Local OIDC configuration created: {destination}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
