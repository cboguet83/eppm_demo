-- Pre-session requests carry purpose-specific server proofs, never actor claims.
SET LOCAL search_path = pg_catalog, eppm, pg_temp;

CREATE FUNCTION eppm.verified_server_request(document text, signature text, purpose text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE secret_key bytea; expected text; request jsonb;
BEGIN
    IF document IS NULL OR length(document) NOT BETWEEN 1 AND 1048576
       OR signature IS NULL OR signature !~ '^[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    SELECT secret INTO secret_key FROM eppm.request_binding_key WHERE singleton;
    IF secret_key IS NULL THEN RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501'; END IF;
    expected := encode(eppm_crypto.hmac(convert_to(document,'UTF8'),secret_key,'sha256'),'hex');
    IF eppm_crypto.digest(signature,'sha256') <> eppm_crypto.digest(expected,'sha256') THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    request := document::jsonb;
    IF (request ->> 'backend')::integer IS DISTINCT FROM pg_backend_pid()
       OR (request ->> 'started')::bigint IS DISTINCT FROM (extract(epoch FROM transaction_timestamp())*1000000)::bigint
       OR request ->> 'purpose' IS DISTINCT FROM purpose
       OR jsonb_typeof(request -> 'payload') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    RETURN request -> 'payload';
EXCEPTION WHEN data_exception THEN
    RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
END $$;

CREATE FUNCTION eppm.require_authentication_writer() RETURNS void
LANGUAGE plpgsql SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    IF current_setting('transaction_isolation') <> 'serializable' OR current_setting('transaction_read_only')='on' THEN
        RAISE EXCEPTION 'Authentication mutations require a serializable transaction' USING ERRCODE='25001';
    END IF;
END $$;

CREATE FUNCTION eppm.oidc_state_store(document text, signature text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE payload jsonb; now_seconds bigint; duration integer;
BEGIN
    payload := eppm.verified_server_request(document,signature,'oidc.state.store');
    PERFORM eppm.require_authentication_writer();
    now_seconds := (payload ->> 'now')::bigint;
    duration := (payload ->> 'duration')::integer;
    IF now_seconds IS NULL OR duration IS NULL OR duration>600
       OR coalesce(payload ->> 'state_hash','') !~ '^[a-f0-9]{64}$'
       OR jsonb_typeof(payload -> 'value') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'Invalid OIDC state request' USING ERRCODE='22023';
    END IF;
    DELETE FROM eppm.app_oidc_state WHERE expires_at<=now_seconds;
    INSERT INTO eppm.app_oidc_state(state_hash,data,expires_at)
        VALUES (payload ->> 'state_hash',payload -> 'value',now_seconds+duration);
END $$;

CREATE FUNCTION eppm.oidc_state_consume(document text, signature text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE payload jsonb; consumed eppm.app_oidc_state; now_seconds bigint;
BEGIN
    payload := eppm.verified_server_request(document,signature,'oidc.state.consume');
    PERFORM eppm.require_authentication_writer();
    now_seconds := (payload ->> 'now')::bigint;
    IF now_seconds IS NULL OR coalesce(payload ->> 'state_hash','') !~ '^[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'Invalid OIDC state request' USING ERRCODE='22023';
    END IF;
    DELETE FROM eppm.app_oidc_state WHERE state_hash=payload ->> 'state_hash' RETURNING * INTO consumed;
    RETURN CASE WHEN consumed.expires_at>now_seconds THEN consumed.data #>> '{}' ELSE NULL END;
END $$;

CREATE FUNCTION eppm.session_lookup(document text, signature text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE payload jsonb; result jsonb;
BEGIN
    payload := eppm.verified_server_request(document,signature,'session.lookup');
    IF coalesce(payload ->> 'session_hash','') !~ '^[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'Invalid session request' USING ERRCODE='22023';
    END IF;
    SELECT jsonb_build_object('session',jsonb_build_object('user_id',s.user_id,'status',u.status,
        'auth_time',s.auth_time,'expires_at',s.expires_at,'last_activity',s.last_activity,'mfa',s.mfa,'revoked',s.revoked),
        'security_revision',(SELECT revision FROM eppm.app_security_state WHERE id=1)) INTO result
        FROM eppm.app_session s JOIN eppm.app_user u ON u.id=s.user_id WHERE s.session_hash=payload ->> 'session_hash';
    RETURN result;
END $$;

CREATE FUNCTION eppm.authenticate_identity(document text, signature text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE payload jsonb; identity jsonb; user_key bigint; now_seconds bigint; expiry bigint;
        account_status text; prior_hash text; current_hash text;
BEGIN
    payload := eppm.verified_server_request(document,signature,'session.sign_in');
    PERFORM eppm.require_authentication_writer();
    identity := payload -> 'identity';
    now_seconds := (payload ->> 'now')::bigint;
    expiry := (payload ->> 'expires_at')::bigint;
    prior_hash := payload ->> 'previous_hash';
    current_hash := payload ->> 'session_hash';
    IF jsonb_typeof(identity) IS DISTINCT FROM 'object' OR now_seconds IS NULL OR expiry IS NULL OR expiry<=now_seconds
       OR (identity ->> 'expires_at')::bigint IS NULL OR (identity ->> 'expires_at')::bigint<=now_seconds
       OR (identity ->> 'auth_time')::bigint IS NULL OR (identity ->> 'auth_time')::bigint>now_seconds+30
       OR jsonb_typeof(identity -> 'mfa') IS DISTINCT FROM 'boolean'
       OR identity ->> 'issuer' IS DISTINCT FROM payload ->> 'configured_issuer'
       OR coalesce(length(trim(identity ->> 'issuer')),0)=0
       OR coalesce(length(trim(identity ->> 'subject')),0)=0 OR length(identity ->> 'subject')>512
       OR identity ->> 'subject' ~ '[[:cntrl:]]'
       OR identity ->> 'email' IS NULL OR length(identity ->> 'email')>320 OR identity ->> 'email' ~ '[[:cntrl:]]'
       OR identity ->> 'display_name' IS NULL OR length(identity ->> 'display_name')>256 OR identity ->> 'display_name' ~ '[[:cntrl:]]'
       OR coalesce(current_hash,'') !~ '^[a-f0-9]{64}$'
       OR prior_hash IS NOT NULL AND prior_hash !~ '^[a-f0-9]{64}$'
       OR coalesce(length(payload ->> 'correlation_id'),0)=0 THEN
        RAISE EXCEPTION 'Invalid verified identity request' USING ERRCODE='22023';
    END IF;
    -- Serialize only this external identity, not unrelated logins or activity.
    PERFORM pg_advisory_xact_lock(hashtextextended((identity ->> 'issuer') || chr(31) || (identity ->> 'subject'), 61795));
    SELECT user_id INTO user_key FROM eppm.app_identity
        WHERE issuer=identity ->> 'issuer' AND subject=identity ->> 'subject';
    IF user_key IS NULL THEN
        INSERT INTO eppm.app_user(created_at,updated_at) VALUES (now_seconds,now_seconds) RETURNING id INTO user_key;
        INSERT INTO eppm.app_identity(user_id,issuer,subject,verified_at)
            VALUES (user_key,identity ->> 'issuer',identity ->> 'subject',now_seconds)
            ON CONFLICT (issuer,subject) DO UPDATE SET verified_at=excluded.verified_at
            RETURNING user_id INTO user_key;
    END IF;
    UPDATE eppm.app_identity SET verified_at=now_seconds WHERE user_id=user_key
        AND issuer=identity ->> 'issuer' AND subject=identity ->> 'subject';
    UPDATE eppm.app_user SET email=identity ->> 'email',display_name=identity ->> 'display_name',updated_at=now_seconds
        WHERE id=user_key RETURNING status INTO account_status;
    IF prior_hash IS NOT NULL THEN UPDATE eppm.app_session SET revoked=true WHERE session_hash=prior_hash; END IF;
    INSERT INTO eppm.app_session(session_hash,user_id,auth_time,expires_at,last_activity,mfa)
        VALUES (current_hash,user_key,(identity ->> 'auth_time')::bigint,expiry,now_seconds,(identity ->> 'mfa')::boolean);
    INSERT INTO eppm.app_security_audit(occurred_at,actor,target,action,outcome,correlation_id,details_json)
        VALUES (now_seconds,'oidc',user_key::text,'authentication.success','success',payload ->> 'correlation_id',
            jsonb_build_object('status',account_status));
    RETURN user_key;
END $$;

CREATE FUNCTION eppm.session_activity() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb;
BEGIN
    PERFORM eppm.require_authentication_writer();
    context := eppm.current_actor(false);
    UPDATE eppm.app_session SET last_activity=(context ->> 'now')::bigint,
        expires_at=(context ->> 'now')::bigint+(context ->> 'idle_seconds')::bigint
        WHERE session_hash=context ->> 'session_hash';
END $$;

CREATE FUNCTION eppm.session_logout() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb;
BEGIN
    PERFORM eppm.require_authentication_writer();
    context := eppm.current_actor(false);
    UPDATE eppm.app_session SET revoked=true WHERE session_hash=context ->> 'session_hash';
    INSERT INTO eppm.app_security_audit(occurred_at,actor,target,action,outcome,correlation_id,details_json)
        VALUES ((context ->> 'now')::bigint,context ->> 'user_id',context ->> 'user_id',
            'session.logout','success',context ->> 'correlation_id','{}');
END $$;

CREATE FUNCTION eppm.policy_scope_projects(document text, signature text) RETURNS bigint[]
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE payload jsonb; context jsonb; scope jsonb;
BEGIN
    payload := eppm.verified_server_request(document,signature,'policy.scope');
    context := eppm.current_actor();
    IF (payload ->> 'user_id')::bigint IS DISTINCT FROM (context ->> 'user_id')::bigint THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    scope := eppm.canonical_scope(payload -> 'scope');
    IF NOT eppm.is_access_administrator() AND NOT EXISTS (
        SELECT 1 FROM eppm.app_role_assignment WHERE user_id=(context ->> 'user_id')::bigint
        AND invalid_reason='' AND eppm.valid_scope_structure(scope_json) AND eppm.canonical_scope(scope_json)=scope
    ) THEN RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501'; END IF;
    -- This trusted server-only projection preserves policy evaluation for a
    -- global non-portfolio permission. Ordinary SQL cannot sign such a request;
    -- public permission helpers and business RLS still hide its project IDs.
    RETURN eppm.resolve_scope(scope);
EXCEPTION WHEN invalid_parameter_value THEN
    -- Expected dangling grants are a typed miss, not an aborted outer snapshot.
    -- The policy can ignore this grant and evaluate other valid assignments.
    RETURN NULL;
END $$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA eppm FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.oidc_state_store(text,text),eppm.oidc_state_consume(text,text),
    eppm.session_lookup(text,text),eppm.authenticate_identity(text,text),eppm.session_activity(),
    eppm.session_logout(),eppm.policy_scope_projects(text,text) TO eppm_runtime;
