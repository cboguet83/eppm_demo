-- Trusted actor context, fixed permission projections, and safe helper paths.
SET LOCAL search_path = pg_catalog, eppm, pg_temp;

DO $$
DECLARE helper regprocedure;
BEGIN
    FOR helper IN SELECT p.oid::regprocedure FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'eppm'
    LOOP
        EXECUTE format('ALTER FUNCTION %s SET search_path = pg_catalog, eppm, pg_temp', helper);
    END LOOP;
END $$;

CREATE SCHEMA eppm_crypto;
CREATE EXTENSION pgcrypto WITH SCHEMA eppm_crypto;
REVOKE ALL ON SCHEMA eppm_crypto FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA eppm_crypto FROM PUBLIC;

CREATE TABLE eppm.request_binding_key (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    secret bytea NOT NULL CHECK (octet_length(secret) = 32)
);
ALTER TABLE eppm.request_binding_key ENABLE ROW LEVEL SECURITY;
-- No runtime policy or privilege can read/modify the signing key.

CREATE TABLE eppm.role_permission (
    role text NOT NULL, permission text NOT NULL, application_wide boolean NOT NULL,
    PRIMARY KEY (role, permission)
);
-- Snapshot generated from app.domain.access.models.ROLE_PERMISSIONS and
-- APPLICATION_ROLES; tests enforce exact parity with those domain definitions.
INSERT INTO eppm.role_permission VALUES
    ('access_admin', 'access.manage', true),
    ('business_admin', 'business.manage', true),
    ('business_admin', 'finance.edit', true),
    ('business_admin', 'project.create', true),
    ('business_admin', 'project.delete', true),
    ('business_admin', 'project.edit', true),
    ('business_admin', 'project.protected_properties', true),
    ('business_admin', 'project.read', true),
    ('finance_editor', 'finance.edit', true),
    ('project_approver', 'project.approve', false),
    ('project_approver', 'project.read', false),
    ('project_editor', 'project.edit', false),
    ('project_editor', 'project.read', false),
    ('project_viewer', 'project.read', false);
ALTER TABLE eppm.role_permission ENABLE ROW LEVEL SECURITY;

CREATE FUNCTION eppm.verified_context(document text, signature text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE secret_key bytea; expected text; context jsonb;
BEGIN
    IF document IS NULL OR length(document) NOT BETWEEN 1 AND 8192
       OR signature IS NULL OR signature !~ '^[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE = '42501';
    END IF;
    SELECT secret INTO secret_key FROM eppm.request_binding_key WHERE singleton;
    IF secret_key IS NULL THEN RAISE EXCEPTION 'Application access denied' USING ERRCODE = '42501'; END IF;
    expected := encode(eppm_crypto.hmac(convert_to(document, 'UTF8'), secret_key, 'sha256'), 'hex');
    -- Hash both fixed-length MACs before equality; prefix timing cannot reveal
    -- successive bytes of the expected MAC.
    IF eppm_crypto.digest(signature, 'sha256') <> eppm_crypto.digest(expected, 'sha256') THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE = '42501';
    END IF;
    context := document::jsonb;
    IF (context ->> 'backend')::integer IS DISTINCT FROM pg_backend_pid()
       OR (context ->> 'started')::bigint IS DISTINCT FROM (extract(epoch FROM transaction_timestamp()) * 1000000)::bigint
       OR (context ->> 'user_id')::bigint IS NULL OR (context ->> 'now')::bigint IS NULL
       OR (context ->> 'idle_seconds')::integer IS NULL OR (context ->> 'idle_seconds')::integer <= 0
       OR (context ->> 'reauthentication_seconds')::integer IS NULL OR (context ->> 'reauthentication_seconds')::integer <= 0
       OR jsonb_typeof(context -> 'admin_mfa') IS DISTINCT FROM 'boolean'
       OR coalesce(length(context ->> 'session_hash'), 0) = 0
       OR coalesce(length(context ->> 'correlation_id'), 0) = 0 THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE = '42501';
    END IF;
    RETURN context;
EXCEPTION WHEN data_exception THEN
    RAISE EXCEPTION 'Application access denied' USING ERRCODE = '42501';
END $$;

CREATE FUNCTION eppm.current_actor(active_required boolean DEFAULT true) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb; session_record record; current_time_seconds bigint;
BEGIN
    context := eppm.verified_context(current_setting('eppm.context', true), current_setting('eppm.signature', true));
    current_time_seconds := (context ->> 'now')::bigint;
    SELECT s.*, u.status INTO session_record FROM eppm.app_session s
        JOIN eppm.app_user u ON u.id = s.user_id WHERE s.session_hash = context ->> 'session_hash';
    IF NOT FOUND OR session_record.user_id IS DISTINCT FROM (context ->> 'user_id')::bigint
       OR session_record.revoked OR current_time_seconds >= session_record.expires_at
       OR current_time_seconds - session_record.last_activity >= (context ->> 'idle_seconds')::integer
       OR session_record.auth_time > current_time_seconds + 30
       OR active_required AND session_record.status <> 'active' THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE = '42501';
    END IF;
    RETURN context || jsonb_build_object('mfa', session_record.mfa, 'status', session_record.status,
        'auth_time', session_record.auth_time, 'expires_at', session_record.expires_at,
        'last_activity', session_record.last_activity);
END $$;

CREATE FUNCTION eppm.bind_actor(document text, signature text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb;
BEGIN
    context := eppm.verified_context(document, signature);
    IF current_setting('transaction_read_only') <> 'on' THEN
        IF current_setting('transaction_isolation') <> 'serializable' THEN
            RAISE EXCEPTION 'Business mutations require a serializable transaction' USING ERRCODE = '25001';
        END IF;
        -- Revocation or disabling that commits before these locks forces the
        -- writer to retry and reauthorize. A later revocation waits for its save.
        PERFORM 1 FROM eppm.app_session s JOIN eppm.app_user u ON u.id = s.user_id
            WHERE s.session_hash = context ->> 'session_hash' FOR SHARE OF s, u;
        PERFORM 1 FROM eppm.app_role_assignment WHERE user_id = (context ->> 'user_id')::bigint
            ORDER BY id FOR SHARE;
    END IF;
    PERFORM set_config('eppm.context', document, true);
    PERFORM set_config('eppm.signature', signature, true);
    PERFORM eppm.current_actor(false);
END $$;

CREATE FUNCTION eppm.permission_scopes(requested_permission text) RETURNS SETOF jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb; assignment record;
BEGIN
    context := eppm.current_actor();
    FOR assignment IN SELECT a.scope_json, p.application_wide FROM eppm.app_role_assignment a
        JOIN eppm.role_permission p ON p.role = a.role
        WHERE a.user_id = (context ->> 'user_id')::bigint AND a.invalid_reason = ''
          AND p.permission = requested_permission ORDER BY a.id
    LOOP
        IF NOT eppm.valid_scope_structure(assignment.scope_json) THEN CONTINUE; END IF;
        IF assignment.application_wide AND (assignment.scope_json ->> 'kind' <> 'all'
           OR (context ->> 'admin_mfa')::boolean AND NOT (context ->> 'mfa')::boolean) THEN CONTINUE; END IF;
        RETURN NEXT assignment.scope_json;
    END LOOP;
END $$;

CREATE FUNCTION eppm.has_global_permission(requested_permission text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
    SELECT EXISTS (SELECT 1 FROM eppm.permission_scopes(requested_permission) scope WHERE scope ->> 'kind' = 'all')
$$;

CREATE FUNCTION eppm.permission_projects(requested_permission text) RETURNS bigint[]
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE scope jsonb; selected bigint[] := ARRAY[]::bigint[];
BEGIN
    FOR scope IN SELECT eppm.permission_scopes(requested_permission)
    LOOP
        BEGIN
            IF scope ->> 'kind' = 'all' THEN RETURN eppm.resolve_scope(scope); END IF;
            selected := selected || eppm.resolve_scope(scope);
        EXCEPTION WHEN invalid_parameter_value THEN
            -- A malformed or dangling grant cannot add permissions.
            CONTINUE;
        END;
    END LOOP;
    RETURN ARRAY(SELECT DISTINCT value FROM unnest(selected) value ORDER BY value);
END $$;

CREATE FUNCTION eppm.has_business_read() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
    SELECT eppm.has_global_permission('project.read') OR cardinality(eppm.permission_projects('project.read')) > 0
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA eppm FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA eppm FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.bind_actor(text,text), eppm.current_actor(boolean),
    eppm.has_global_permission(text), eppm.permission_projects(text), eppm.has_business_read() TO eppm_runtime;
