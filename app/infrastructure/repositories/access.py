"""SQLite access persistence; no identity claims or permissions come from the UI."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing, contextmanager
import json
import sqlite3

from app.application.ports.access import AssignmentRecord, SessionRecord, UserRecord
from app.domain.access.models import ProjectScope, VerifiedIdentity
from app.infrastructure.database.connection import get_db


class SqliteAccessStore:
    """Use one explicit connection for policy checks, security writes, and audit."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def _execute(self, statement: str, parameters: Sequence[object] = ()) -> sqlite3.Cursor:
        """Use named security rows without changing the caller's business row factory."""
        cursor = self.connection.cursor()
        cursor.row_factory = sqlite3.Row
        return cursor.execute(statement, parameters)

    def find_user(self, user_id: int) -> UserRecord | None:
        """Read an internal user without disclosing external identity payloads."""
        row = self._execute("SELECT * FROM app_user WHERE id=?", (user_id,)).fetchone()
        return UserRecord(**dict(row)) if row else None

    def list_users(self, search: str, limit: int = 100, *, after_id: int = 0,
                   status: str | None = None) -> list[UserRecord]:
        """Filter account status and continuation reference before bounding results."""
        rows = self._execute(
            "SELECT * FROM app_user WHERE id>? AND (? IS NULL OR status=?) AND "
            "(instr(lower(display_name),lower(?))>0 OR instr(lower(email),lower(?))>0 "
            "OR CAST(id AS TEXT)=?) ORDER BY id LIMIT ?",
            (after_id, status, status, search, search, search, min(max(limit, 1), 200)),
        )
        return [UserRecord(**dict(row)) for row in rows]

    def register_user(self, issuer: str, subject: str, display_name: str, now: int) -> int:
        """Pre-register an exact issuer/subject as pending, without a verified login."""
        user = self._execute(
            "INSERT INTO app_user(display_name,created_at,updated_at) VALUES(?,?,?)",
            (display_name, now, now),
        ).lastrowid
        self._execute("INSERT INTO app_identity(user_id,issuer,subject) VALUES(?,?,?)", (user, issuer, subject))
        return int(user)

    def resolve_identity(self, identity: VerifiedIdentity, now: int) -> UserRecord:
        """Resolve issuer and subject only; update profile fields without changing state."""
        row = self._execute("SELECT user_id FROM app_identity WHERE issuer=? AND subject=?",
                                      (identity.issuer, identity.subject)).fetchone()
        user_id = int(row[0]) if row else self.register_user(identity.issuer, identity.subject, identity.display_name, now)
        self._execute("UPDATE app_identity SET verified_at=? WHERE issuer=? AND subject=?",
                                (now, identity.issuer, identity.subject))
        self._execute("UPDATE app_user SET email=?,display_name=?,updated_at=? WHERE id=?",
                                (identity.email, identity.display_name, now, user_id))
        result = self.find_user(user_id)
        assert result is not None
        return result

    def verified_user(self, user_id: int) -> bool:
        """Bootstrap and recovery require an account with a verified OIDC login."""
        return bool(self._execute("SELECT 1 FROM app_identity WHERE user_id=? AND verified_at IS NOT NULL",
                                            (user_id,)).fetchone())

    def set_status(self, user_id: int, status: str, now: int) -> None:
        """Change state; application policy owns activation and continuity checks."""
        self._execute("UPDATE app_user SET status=?,updated_at=? WHERE id=?", (status, now, user_id))

    def assignments(self, user_id: int) -> list[AssignmentRecord]:
        """Read current grants; never cache authorization at login time."""
        return [AssignmentRecord(**dict(row)) for row in self._execute(
            "SELECT * FROM app_role_assignment WHERE user_id=? ORDER BY id", (user_id,))]

    def assignment(self, assignment_id: int) -> AssignmentRecord | None:
        """Read one grant for an authoritative revocation operation."""
        row = self._execute("SELECT * FROM app_role_assignment WHERE id=?", (assignment_id,)).fetchone()
        return AssignmentRecord(**dict(row)) if row else None

    def grant(self, user_id: int, role: str, scope: ProjectScope, now: int, actor: str) -> int:
        """Persist a canonical validated scope alongside its permission-bearing role."""
        encoded = json.dumps(scope.to_dict(), sort_keys=True, separators=(",", ":"))
        self._execute("INSERT OR IGNORE INTO app_role_assignment(user_id,role,scope_json,created_at,created_by) VALUES(?,?,?,?,?)",
                                (user_id, role, encoded, now, actor))
        return int(self._execute("SELECT id FROM app_role_assignment WHERE user_id=? AND role=? AND scope_json=?",
                                           (user_id, role, encoded)).fetchone()[0])

    def revoke(self, assignment_id: int) -> None:
        """Remove a positive grant inside the caller's transaction."""
        self._execute("DELETE FROM app_role_assignment WHERE id=?", (assignment_id,))

    def active_admin_count(self) -> int:
        """Count distinct active access administrators, not their assignments."""
        return int(self._execute("SELECT count(DISTINCT u.id) FROM app_user u JOIN app_role_assignment a "
                                           "ON a.user_id=u.id WHERE u.status='active' AND a.role='access_admin'").fetchone()[0])

    def security_revision(self) -> int:
        """Read the revision advanced atomically by security and protected-scope changes."""
        return int(self._execute("SELECT revision FROM app_security_state WHERE id=1").fetchone()[0])

    def bootstrap_complete(self) -> bool:
        """Any existing access-administrator assignment permanently blocks initial bootstrap."""
        row = self._execute("SELECT bootstrap_complete FROM app_security_state WHERE id=1").fetchone()
        if row is None:
            raise ValueError("Access schema is unavailable.")
        return bool(row[0] or self._execute("SELECT 1 FROM app_role_assignment WHERE role='access_admin'").fetchone())

    def finish_bootstrap(self) -> None:
        """Record completion; no application method clears this marker."""
        self._execute("UPDATE app_security_state SET bootstrap_complete=1 WHERE id=1")

    def session(self, session_hash: str) -> SessionRecord | None:
        """Read session timing together with the current account state."""
        row = self._execute("SELECT s.user_id,u.status,s.auth_time,s.expires_at,s.last_activity,s.mfa,s.revoked "
                                      "FROM app_session s JOIN app_user u ON u.id=s.user_id WHERE s.session_hash=?", (session_hash,)).fetchone()
        return SessionRecord(**dict(row)) if row else None

    def create_session(self, session_hash: str, user_id: int, identity: VerifiedIdentity, now: int, expires_at: int) -> None:
        """Store only the opaque reference and verified timing/MFA information."""
        self._execute("INSERT INTO app_session(session_hash,user_id,auth_time,expires_at,last_activity,mfa) VALUES(?,?,?,?,?,?)",
                                (session_hash, user_id, identity.auth_time, expires_at, now, int(identity.mfa)))

    def revoke_session(self, session_hash: str) -> None:
        """Invalidate the browser session across its open tabs and reconnects."""
        self._execute("UPDATE app_session SET revoked=1 WHERE session_hash=?", (session_hash,))

    def touch_session(self, session_hash: str, now: int, expires_at: int) -> None:
        """Record explicit user activity, never background permission checks."""
        self._execute("UPDATE app_session SET last_activity=?,expires_at=? WHERE session_hash=?", (now, expires_at, session_hash))

    def scope_projects(self, scope: ProjectScope) -> set[int]:
        """Resolve all references first, then intersect current matching project IDs."""
        if scope.kind == "all":
            return {int(row[0]) for row in self._execute("SELECT id FROM main.project")}
        if scope.kind == "projects":
            found = {int(row[0]) for row in self._execute(
                "SELECT id FROM main.project WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(scope.project_ids),))}
            if len(found) != len(scope.project_ids):
                raise ValueError("Scope contains a missing project reference.")
            return found
        matches: set[int] | None = None
        for condition in scope.conditions:
            ids = json.dumps(condition.value_ids)
            if condition.property_id == "project_type_id":
                count = self._execute("SELECT count(*) FROM main.project_type WHERE id IN (SELECT value FROM json_each(?))", (ids,)).fetchone()[0]
                rows = self._execute("SELECT id FROM main.project WHERE project_type_id IN (SELECT value FROM json_each(?))", (ids,))
            else:
                key = condition.property_id.removeprefix("enum:")
                if not condition.property_id.startswith("enum:") or not key.isascii() or not key.isdecimal():
                    raise ValueError("Property is not in the scope allowlist.")
                row = self._execute("SELECT p.param_id FROM main.app_scope_property a JOIN main.schema_parameters p ON p.param_id=a.param_id "
                                              "WHERE a.id=? AND p.param_type='ENUM'", (int(key),)).fetchone()
                if row is None:
                    raise ValueError("Scope contains a missing or unsupported property.")
                param = row[0]
                count = self._execute("SELECT count(*) FROM main.schema_param_options WHERE param_id=? AND id IN (SELECT value FROM json_each(?))", (param, ids)).fetchone()[0]
                rows = self._execute("SELECT v.project_id FROM main.project_property_value v JOIN main.schema_param_options o "
                    "ON o.param_id=v.param_id AND o.option_value=v.text_value WHERE v.kind='text' AND v.param_id=? "
                    "AND o.id IN (SELECT value FROM json_each(?))", (param, ids))
            if count != len(condition.value_ids):
                raise ValueError("Scope contains a missing categorical value.")
            found = {int(row[0]) for row in rows}
            matches = found if matches is None else matches & found
        return matches or set()

    def scope_catalog(self) -> list[dict[str, object]]:
        """Expose only stable single-valued categorical references eligible for scopes."""
        result: list[dict[str, object]] = [{"property_id": "project_type_id", "label": "Project template",
            "values": [dict(row) for row in self._execute("SELECT id,name AS label FROM main.project_type ORDER BY id")]}]
        options: dict[str, list[dict[str, object]]] = {}
        for row in self._execute("SELECT id,param_id,option_value FROM main.schema_param_options ORDER BY id"):
            options.setdefault(row[1], []).append({"id": row[0], "label": row[2]})
        for row in self._execute("SELECT a.id,p.param_id,p.param_name FROM main.app_scope_property a "
                                           "JOIN main.schema_parameters p ON p.param_id=a.param_id WHERE p.param_type='ENUM' ORDER BY a.id"):
            result.append({"property_id": f"enum:{row[0]}", "label": row[2], "param_id": row[1],
                           "values": options.get(row[1], [])})
        return result

    def scope_project_choices(self, search: str) -> list[dict[str, object]]:
        """Return only bounded project IDs/names for configuring named scopes."""
        rows = self._execute(
            "SELECT id,name FROM main.project WHERE instr(lower(name),lower(?))>0 OR CAST(id AS TEXT)=? ORDER BY id LIMIT 100",
            (search, search),
        )
        return [dict(row) for row in rows]

    def audit(self, now: int, actor: str, target: str, action: str, correlation_id: str,
              details: Mapping[str, object], outcome: str = "success") -> None:
        """Append required audit in the same transaction; failure aborts its mutation."""
        self._execute("INSERT INTO app_security_audit(occurred_at,actor,target,action,outcome,correlation_id,details_json) VALUES(?,?,?,?,?,?,?)",
            (now, actor, target, action, outcome, correlation_id, json.dumps(dict(details), ensure_ascii=True, sort_keys=True)))
        # These events change one session, whose validity is checked directly on
        # every transport message. They do not change anyone's permissions and
        # must not invalidate unrelated Streamlit runtimes or display caches.
        if action not in {"authentication.success", "session.logout"}:
            self._execute("UPDATE app_security_state SET revision=revision+1 WHERE id=1")

    def list_audit(self, limit: int = 100) -> list[dict[str, object]]:
        """Read a bounded audit history; no update/delete API exists."""
        return [dict(row) for row in self._execute("SELECT * FROM app_security_audit ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 500),))]


class SqliteAccessGateway:
    """Use actual SQLite transactions and writer serialization for security changes."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[SqliteAccessStore]:
        """Close every connection and roll back any policy, integrity, or audit failure."""
        with closing(get_db(self.db_path)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield SqliteAccessStore(connection)
