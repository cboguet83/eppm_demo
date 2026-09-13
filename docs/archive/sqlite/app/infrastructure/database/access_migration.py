"""Add application identities, positive grants, persistent sessions, and audit."""

import sqlite3


def migrate_access(connection: sqlite3.Connection) -> None:
    """Apply the access schema in the existing migration transaction, exactly once."""
    version = "oidc-access-v1"
    if connection.execute("SELECT 1 FROM schema_migration WHERE version=?", (version,)).fetchone():
        return
    statements = (
        """CREATE TABLE app_user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','active','disabled')),
            email TEXT NOT NULL DEFAULT '', display_name TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""",
        """CREATE TABLE app_identity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE RESTRICT,
            issuer TEXT NOT NULL CHECK(length(issuer)>0),
            subject TEXT NOT NULL CHECK(length(subject)>0), verified_at INTEGER,
            UNIQUE(issuer, subject))""",
        """CREATE TABLE app_role_assignment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE RESTRICT,
            role TEXT NOT NULL CHECK(role IN ('project_viewer','project_editor','project_approver','access_admin','business_admin')),
            scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),
            invalid_reason TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL, created_by TEXT NOT NULL,
            UNIQUE(user_id, role, scope_json))""",
        """CREATE TABLE app_security_state (
            id INTEGER PRIMARY KEY CHECK(id=1),
            bootstrap_complete INTEGER NOT NULL DEFAULT 0 CHECK(bootstrap_complete IN (0,1)),
            revision INTEGER NOT NULL DEFAULT 0)""",
        "INSERT INTO app_security_state(id) VALUES (1)",
        """CREATE TRIGGER app_complete_initial_setup AFTER INSERT ON app_role_assignment
            WHEN NEW.role='access_admin'
            BEGIN UPDATE app_security_state SET bootstrap_complete=1 WHERE id=1; END""",
        """CREATE TABLE app_session (
            session_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE RESTRICT,
            auth_time INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            last_activity INTEGER NOT NULL, mfa INTEGER NOT NULL CHECK(mfa IN (0,1)),
            revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)))""",
        """CREATE TABLE app_security_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at INTEGER NOT NULL,
            actor TEXT NOT NULL, target TEXT NOT NULL, action TEXT NOT NULL,
            outcome TEXT NOT NULL, correlation_id TEXT NOT NULL, details_json TEXT NOT NULL CHECK(json_valid(details_json)))""",
        """CREATE TRIGGER app_audit_no_update BEFORE UPDATE ON app_security_audit
            BEGIN SELECT RAISE(ABORT, 'Security audit records are immutable'); END""",
        """CREATE TRIGGER app_audit_no_delete BEFORE DELETE ON app_security_audit
            BEGIN SELECT RAISE(ABORT, 'Security audit records are immutable'); END""",
        "CREATE INDEX app_assignment_user ON app_role_assignment(user_id)",
        "CREATE INDEX app_identity_user ON app_identity(user_id)",
        "CREATE INDEX app_session_user ON app_session(user_id)",
        """CREATE TABLE app_oidc_state (
            state_hash TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)),
            expires_at INTEGER NOT NULL)""",
        "CREATE INDEX app_oidc_state_expiry ON app_oidc_state(expires_at)",
        "CREATE INDEX app_audit_time ON app_security_audit(occurred_at,id)",
        """CREATE TABLE app_scope_property (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            param_id TEXT UNIQUE REFERENCES schema_parameters(param_id) ON DELETE SET NULL)""",
        "INSERT INTO app_scope_property(param_id) SELECT param_id FROM schema_parameters WHERE param_type='ENUM'",
        """CREATE TRIGGER app_register_enum_insert AFTER INSERT ON schema_parameters
            WHEN NEW.param_type='ENUM'
            BEGIN INSERT OR IGNORE INTO app_scope_property(param_id) VALUES(NEW.param_id); END""",
        """CREATE TRIGGER app_register_enum_update AFTER UPDATE OF param_type ON schema_parameters
            WHEN NEW.param_type='ENUM'
            BEGIN INSERT OR IGNORE INTO app_scope_property(param_id) VALUES(NEW.param_id); END""",
        """CREATE TRIGGER app_invalidate_deleted_project BEFORE DELETE ON project
            BEGIN UPDATE app_role_assignment SET invalid_reason='A selected project was deleted. Revoke and recreate this assignment.'
            WHERE json_extract(scope_json,'$.kind')='projects' AND EXISTS (
                SELECT 1 FROM json_each(scope_json,'$.project_ids') WHERE value=OLD.id); END""",
        """CREATE TRIGGER app_invalidate_deleted_type BEFORE DELETE ON project_type
            BEGIN UPDATE app_role_assignment SET invalid_reason='A selected project type was deleted. Revoke and recreate this assignment.'
            WHERE EXISTS (SELECT 1 FROM json_each(scope_json,'$.conditions') c,
                json_each(c.value,'$.value_ids') v
                WHERE json_extract(c.value,'$.property_id')='project_type_id' AND v.value=OLD.id); END""",
        """CREATE TRIGGER app_invalidate_deleted_option BEFORE DELETE ON schema_param_options
            BEGIN UPDATE app_role_assignment SET invalid_reason='A selected categorical value was deleted. Revoke and recreate this assignment.'
            WHERE EXISTS (SELECT 1 FROM json_each(scope_json,'$.conditions') c,
                json_each(c.value,'$.value_ids') v JOIN app_scope_property p ON p.param_id=OLD.param_id
                WHERE json_extract(c.value,'$.property_id')='enum:'||p.id AND v.value=OLD.id); END""",
        """CREATE TRIGGER app_invalidate_changed_option BEFORE UPDATE OF param_id,option_value ON schema_param_options
            WHEN OLD.param_id IS NOT NEW.param_id OR OLD.option_value IS NOT NEW.option_value
            BEGIN UPDATE app_role_assignment SET invalid_reason='A selected categorical value was replaced. Revoke and recreate this assignment.'
            WHERE EXISTS (SELECT 1 FROM json_each(scope_json,'$.conditions') c,
                json_each(c.value,'$.value_ids') v JOIN app_scope_property p ON p.param_id=OLD.param_id
                WHERE json_extract(c.value,'$.property_id')='enum:'||p.id AND v.value=OLD.id); END""",
        """CREATE TRIGGER app_tombstone_deleted_property BEFORE DELETE ON schema_parameters
            BEGIN UPDATE app_scope_property SET param_id=NULL WHERE param_id=OLD.param_id; END""",
        """CREATE TRIGGER app_tombstone_retyped_property BEFORE UPDATE OF param_type ON schema_parameters
            WHEN OLD.param_type='ENUM' AND NEW.param_type!='ENUM'
            BEGIN UPDATE app_scope_property SET param_id=NULL WHERE param_id=OLD.param_id; END""",
    )
    for statement in statements:
        connection.execute(statement)
    connection.execute("INSERT INTO schema_migration(version) VALUES (?)", (version,))
