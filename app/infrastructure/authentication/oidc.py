"""Authlib OIDC integration with explicit provider and token validation policy."""

from collections.abc import Callable
from typing import Any

from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from authlib.integrations.starlette_client.integration import StarletteIntegration
from starlette.requests import Request

from app.domain.access.models import AccessDenied, VerifiedIdentity
from app.infrastructure.authentication.state import SqliteOidcState
from app.shared.config.authentication import AuthenticationConfig, validate_url


class ConfiguredOidcClient(StarletteOAuth2App):
    """Use Authlib protocol validation while pinning the deployment's trust policy.

    Authlib's dynamic metadata/token dictionaries are the deliberate ``Any`` boundary.
    Tokens and arbitrary claims never leave this adapter.
    """

    def __init__(self, framework: StarletteIntegration, name: str, *,
                 authentication: AuthenticationConfig, **kwargs: Any) -> None:
        self.authentication = authentication
        super().__init__(framework, name, **kwargs)

    async def load_server_metadata(self) -> dict[str, Any]:
        """Reject changed issuers, unsafe endpoints, and unsupported protocol choices."""
        metadata = await super().load_server_metadata()
        if metadata.get("issuer") != self.authentication.issuer:
            raise AccessDenied()
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            value = metadata.get(name)
            if not isinstance(value, str):
                raise AccessDenied()
            validate_url(value, local=self.authentication.local_http)
        if "code" not in metadata.get("response_types_supported", []):
            raise AccessDenied()
        if "S256" not in metadata.get("code_challenge_methods_supported", []):
            raise AccessDenied()
        advertised = metadata.get("id_token_signing_alg_values_supported", [])
        allowed = [alg for alg in self.authentication.algorithms if alg in advertised]
        if not allowed:
            raise AccessDenied()
        # Authlib constructs its JOSE registry from this field, including JWKS refresh.
        metadata["id_token_signing_alg_values_supported"] = allowed
        return metadata

    async def parse_id_token(self, token: dict[str, Any], nonce: str,
                             claims_options: dict[str, Any] | None = None,
                             claims_cls: type | None = None, leeway: int = 0) -> dict[str, Any]:
        """Require exact issuer, audience, nonce and authentication time in verified claims."""
        if not isinstance(nonce, str) or not nonce:
            raise AccessDenied()
        options = {
            "iss": {"essential": True, "value": self.authentication.issuer},
            "aud": {"essential": True, "value": self.authentication.client_id},
            # Explicit nonce validation also rejects nonce_supported=false downgrades.
            "nonce": {"essential": True, "value": nonce},
            "auth_time": {"essential": True},
        }
        return await super().parse_id_token(token, nonce, options, claims_cls, leeway=0)


def create_oidc_client(config: AuthenticationConfig, db_path: str,
                       clock: Callable[[], int]) -> ConfiguredOidcClient:
    """Compose the maintained OAuth client with single-use server-side PKCE state."""
    oauth = OAuth(cache=SqliteOidcState(db_path, clock))
    return oauth.register(
        "provider", client_cls=ConfiguredOidcClient, authentication=config,
        client_id=config.client_id, client_secret=config.client_secret,
        server_metadata_url=config.discovery_url,
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256",
                       "token_endpoint_auth_method": "client_secret_basic", "timeout": 10.0},
    )


async def verified_identity(client: ConfiguredOidcClient, request: Request) -> VerifiedIdentity:
    """Exchange the authorization code and return only verified minimal identity claims."""
    if str(request.url).split("?", 1)[0] != client.authentication.callback_url:
        raise AccessDenied()
    if any(len(request.query_params.getlist(name)) > 1 for name in ("code", "state", "iss", "error")):
        raise AccessDenied()
    metadata = await client.load_server_metadata()
    issuer = request.query_params.get("iss")
    if (issuer is not None or metadata.get("authorization_response_iss_parameter_supported")) and issuer != client.authentication.issuer:
        raise AccessDenied()
    token = await client.authorize_access_token(request, leeway=0)
    claims = token.get("userinfo")
    if not isinstance(claims, dict):
        raise AccessDenied()
    if any(type(claims.get(name)) is not int for name in ("auth_time", "exp", "iat")):
        raise AccessDenied()
    return VerifiedIdentity(
        issuer=claims["iss"], subject=claims["sub"],
        email=claims.get("email", ""), display_name=claims.get("name", ""),
        auth_time=claims["auth_time"], expires_at=claims["exp"],
        mfa=isinstance(claims.get("acr"), str) and claims["acr"] in client.authentication.mfa_acr_values,
    )
