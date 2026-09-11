"""Validated deployment settings for one OIDC provider and application origin."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import hmac
from urllib.parse import urlsplit


def validate_url(value: str, *, local: bool) -> None:
    """Require HTTPS, with an explicit loopback-only development exception."""
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError("Invalid authentication URL.") from None
    if (not url.hostname or url.username is not None or url.password is not None
            or url.fragment or url.query or any(char.isspace() for char in value)
            or "\\" in value or (port is not None and port <= 0)):
        raise ValueError("Invalid authentication URL.")
    loopback = url.hostname in {"localhost", "127.0.0.1", "::1"} or url.hostname.endswith(".localhost")
    if url.scheme != "https" and not (local and loopback and url.scheme == "http"):
        raise ValueError("Authentication URLs require HTTPS outside explicit local development.")


@dataclass(frozen=True)
class AuthenticationConfig:
    """Fail-closed OIDC and session settings, loaded explicitly at composition."""

    environment: str
    issuer: str
    client_id: str
    client_secret: str = field(repr=False)
    origin: str
    cookie_secret: str = field(repr=False)
    local_http: bool = False
    idle_seconds: int = 900
    reauthentication_seconds: int = 300
    algorithms: tuple[str, ...] = ("RS256",)
    mfa_acr_values: tuple[str, ...] = ()

    def session_binding(self, session_hash: str, status: str, revision: int) -> str:
        """Sign the server-only connection identity used to bind Streamlit reconnects."""
        message = f"eppm-streamlit-session:{session_hash}:{status}:{revision}".encode("utf-8")
        return hmac.digest(self.cookie_secret.encode("utf-8"), message, "sha256").hex()

    def __post_init__(self) -> None:
        if self.environment not in {"development", "staging", "production"}:
            raise ValueError("Unknown application environment.")
        if self.local_http and self.environment != "development":
            raise ValueError("HTTP authentication is allowed only in local development.")
        validate_url(self.issuer, local=self.local_http)
        validate_url(self.origin, local=self.local_http)
        if self.issuer.endswith("/") or urlsplit(self.origin).path:
            raise ValueError("Use an exact issuer and an application origin without a trailing slash or path.")
        for name, value, minimum in (("client ID", self.client_id, 1),
                                      ("client secret", self.client_secret, 16),
                                      ("cookie secret", self.cookie_secret, 32)):
            if (len(value) < minimum or value != value.strip() or len(value) > 4096
                    or any(ord(char) < 32 for char in value)
                    or value.lower().startswith(("replace", "change", "your_", "<"))):
                raise ValueError(f"Configure a valid OIDC {name}.")
        if (not self.algorithms or not set(self.algorithms) <= {"RS256", "PS256", "ES256"}):
            raise ValueError("Select an explicitly supported asymmetric signing algorithm.")
        limits = (self.idle_seconds, self.reauthentication_seconds)
        if any(type(value) is not int or value <= 0 for value in limits):
            raise ValueError("Session limits must be positive integer seconds.")
        if self.environment != "development" and not self.mfa_acr_values:
            raise ValueError("Configure provider-attested MFA ACR values for production administrators.")

    @property
    def callback_url(self) -> str:
        """Return the single exact, deployment-controlled redirect URI."""
        return self.origin + "/auth/callback"

    @property
    def discovery_url(self) -> str:
        """Use discovery at the configured issuer, never a browser-supplied URL."""
        return self.issuer + "/.well-known/openid-configuration"

    @property
    def secure_cookies(self) -> bool:
        """Only explicit local HTTP deployment may omit the Secure attribute."""
        return urlsplit(self.origin).scheme == "https"

    @classmethod
    def from_environment(cls, values: Mapping[str, str]) -> AuthenticationConfig:
        """Read typed settings without implicit Streamlit secrets-file behavior."""
        required = ("APP_ENV", "OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET",
                    "APP_ORIGIN", "APP_COOKIE_SECRET")
        if any(not values.get(name) for name in required):
            raise ValueError("Configure APP_ENV, APP_ORIGIN, APP_COOKIE_SECRET and the OIDC issuer/client settings.")
        local_http = values.get("OIDC_ALLOW_LOCAL_HTTP", "false").lower()
        if local_http not in {"true", "false"}:
            raise ValueError("OIDC_ALLOW_LOCAL_HTTP must be true or false.")
        try:
            limits = {name: int(values.get(key, default)) for name, key, default in (
                ("idle_seconds", "SESSION_IDLE_SECONDS", "900"),
                ("reauthentication_seconds", "SESSION_REAUTHENTICATION_SECONDS", "300"),
            )}
        except ValueError:
            raise ValueError("Session settings must be integer seconds.") from None
        return cls(
            environment=values["APP_ENV"], issuer=values["OIDC_ISSUER"],
            client_id=values["OIDC_CLIENT_ID"], client_secret=values["OIDC_CLIENT_SECRET"],
            origin=values["APP_ORIGIN"], cookie_secret=values["APP_COOKIE_SECRET"],
            local_http=local_http == "true", **limits,
            algorithms=tuple(values.get("OIDC_SIGNING_ALGORITHMS", "RS256").split(",")),
            mfa_acr_values=tuple(value.strip() for value in values.get("OIDC_MFA_ACR_VALUES", "").split(",") if value.strip()),
        )
