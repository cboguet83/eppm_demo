"""Pre-session native functions cannot be used as an unsigned SQL bypass."""

import hmac
import json

import psycopg
import pytest

from app.infrastructure.postgresql.authorization import ServerRequestSigner


@pytest.mark.parametrize("function", ["oidc_state_store", "oidc_state_consume", "session_lookup", "authenticate_identity", "policy_scope_projects"])
def test_runtime_cannot_invoke_server_operations_without_a_proof(authorized, function):
    query = psycopg.sql.SQL("SELECT eppm.{}(%s,%s)").format(psycopg.sql.Identifier(function))
    for proof in [(None, None), ("{}", "0" * 64), ("malformed", "bad")]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            authorized.database.run(lambda connection: connection.execute(query, proof), write=True)


@pytest.mark.parametrize("change", ["payload", "purpose", "backend", "started"])
def test_proof_tampering_fails_even_on_the_original_connection(authorized, change):
    signer = ServerRequestSigner(authorized.key)

    def attempt(connection):
        document, signature = signer.sign(connection, "session.lookup", {"session_hash": "a" * 64})
        values = json.loads(document)
        values[change] = {"session_hash": "b" * 64} if change == "payload" else "changed"
        connection.execute("SELECT eppm.session_lookup(%s,%s)", (json.dumps(values), signature))

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.database.run(attempt)


def test_proof_cannot_be_replayed_on_another_transaction_or_connection(authorized):
    signer = ServerRequestSigner(authorized.key)
    proof = authorized.database.run(lambda connection: signer.sign(connection, "session.lookup", {"session_hash": "a" * 64}))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        authorized.database.run(lambda connection: connection.execute("SELECT eppm.session_lookup(%s,%s)", proof))

    def cross_connection(connection):
        proof = signer.sign(connection, "session.lookup", {"session_hash": "a" * 64})
        with psycopg.connect(authorized.setup.runtime_url) as other:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                other.execute("SELECT eppm.session_lookup(%s,%s)", proof)

    authorized.database.run(cross_connection)


def test_valid_server_proof_cannot_be_used_for_another_purpose_or_as_an_actor(authorized):
    signer = ServerRequestSigner(authorized.key)
    for query in ("SELECT eppm.oidc_state_consume(%s,%s)", "SELECT eppm.bind_actor(%s,%s)"):
        def attempt(connection):
            proof = signer.sign(connection, "session.lookup", {"session_hash": "a" * 64})
            connection.execute(query, proof)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            authorized.database.run(attempt, write=True)


@pytest.mark.parametrize("document", ["not JSON", "[]", '{"backend":"not an integer"}'])
def test_signed_malformed_envelopes_fail_with_safe_permission_error(authorized, document):
    signature = hmac.digest(authorized.key, document.encode(), "sha256").hex()
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="Application access denied"):
        authorized.database.run(lambda connection: connection.execute("SELECT eppm.session_lookup(%s,%s)", (document, signature)))


def test_server_scope_proof_cannot_resolve_another_actors_or_unassigned_scope(authorized):
    signer = ServerRequestSigner(authorized.key)
    for payload in ({"user_id": 2, "scope": {"kind": "projects", "project_ids": [3]}},
                    {"user_id": 1, "scope": {"kind": "all"}}):
        def attempt(connection):
            proof = signer.sign(connection, "policy.scope", payload)
            connection.execute("SELECT eppm.policy_scope_projects(%s,%s)", proof)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            authorized.database.run(attempt, bind=authorized.binding())


@pytest.mark.parametrize("table", ["app_session", "app_identity", "app_oidc_state", "request_binding_key"])
def test_runtime_cannot_read_or_change_private_authentication_rows(authorized, table):
    for template in ("SELECT * FROM eppm.{}", "DELETE FROM eppm.{}"):
        query = psycopg.sql.SQL(template).format(psycopg.sql.Identifier(table))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            authorized.database.run(lambda connection: connection.execute(query), write=True, bind=authorized.binding(5))


def test_native_state_mutations_require_serializable_write_transaction(authorized):
    signer = ServerRequestSigner(authorized.key)
    def attempt(connection):
        proof = signer.sign(connection, "oidc.state.consume", {"state_hash": "a" * 64, "now": 1000})
        connection.execute("SELECT eppm.oidc_state_consume(%s,%s)", proof)
    with pytest.raises(psycopg.errors.ActiveSqlTransaction):
        authorized.database.run(attempt)
