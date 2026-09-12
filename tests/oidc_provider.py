"""Shared external-provider transport; Authlib, JOSE and persistence remain real."""

from base64 import urlsafe_b64encode
from hashlib import sha256
import secrets
from typing import Any
from urllib.parse import parse_qs

import httpx2 as httpx
from joserfc import jwt
from joserfc.jwk import RSAKey

from app.infrastructure.authentication.oidc import ConfiguredOidcClient, OidcStateCache, create_oidc_client
from app.shared.config.authentication import AuthenticationConfig


def oidc_provider(config: AuthenticationConfig, cache: OidcStateCache,
                  now: list[int]) -> tuple[ConfiguredOidcClient, dict[str, Any]]:
    """Replace only provider HTTP; dynamic claims intentionally form an Any boundary."""
    provider = create_oidc_client(config, cache)
    signing = RSAKey.generate_key(2048, parameters={"kid": "initial"})
    metadata = {"issuer": config.issuer, "authorization_endpoint": config.issuer + "/authorize",
                "token_endpoint": config.issuer + "/token", "jwks_uri": config.issuer + "/keys",
                "response_types_supported": ["code"], "code_challenge_methods_supported": ["S256"],
                "id_token_signing_alg_values_supported": ["RS256", "HS256", "none"],
                "authorization_response_iss_parameter_supported": True}
    state = {"key": signing, "jwks": [signing.as_dict(private=False)], "metadata": metadata,
             "claims": {}, "authorization": {}, "exchanges": 0, "key_fetches": 0}

    def remote(request: httpx.Request) -> httpx.Response:
        if request.url == config.discovery_url:
            return httpx.Response(200, json=state["metadata"])
        if request.url == metadata["jwks_uri"]:
            state["key_fetches"] += 1
            return httpx.Response(200, json={"keys": state["jwks"]})
        assert str(request.url) == metadata["token_endpoint"]
        state["exchanges"] += 1
        body = parse_qs(request.content.decode())
        assert body["redirect_uri"] == [config.callback_url]
        challenge = urlsafe_b64encode(sha256(body["code_verifier"][0].encode()).digest()).rstrip(b"=").decode()
        assert [challenge] == state["authorization"]["code_challenge"]
        assert body["grant_type"] == ["authorization_code"]
        claims = {"iss": config.issuer, "sub": "verified-test-subject", "aud": config.client_id,
                  "azp": config.client_id, "iat": now[0], "exp": now[0] + 3600, "auth_time": now[0],
                  "nonce": state["authorization"]["nonce"][0], "acr": "2", "name": "Fictional User",
                  "email": "fictional@example.test", **state["claims"]}
        claims = {key: value for key, value in claims.items() if value is not None}
        signed = jwt.encode({"alg": "RS256", "kid": state["key"].kid}, claims, state["key"])
        state["signed"] = signed
        token = {"access_token": secrets.token_urlsafe(24), "token_type": "Bearer"}
        if not state.get("omit_id_token"):
            token["id_token"] = signed
        if state.get("plain_userinfo"):
            token["userinfo"] = state.get("userinfo_claims", claims)
        return httpx.Response(200, json=token)

    provider.client_kwargs["transport"] = httpx.MockTransport(remote)
    return provider, state
