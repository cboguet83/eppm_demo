-- Bounded administration functions own their authorization, continuity and audit.
SET LOCAL search_path = pg_catalog, eppm, pg_temp;

CREATE FUNCTION eppm.is_access_administrator() RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    IF eppm.current_actor(false) ->> 'status' <> 'active' THEN RETURN false; END IF;
    RETURN eppm.has_global_permission('access.manage');
END $$;

CREATE FUNCTION eppm.lock_access_administration() RETURNS void
LANGUAGE plpgsql SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    IF current_setting('transaction_isolation') <> 'serializable' THEN
        RAISE EXCEPTION 'Access mutations require a serializable transaction' USING ERRCODE='25001';
    END IF;
    PERFORM pg_advisory_xact_lock(4994576949004550483);
END $$;

CREATE FUNCTION eppm.require_access_administration(recent boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb;
BEGIN
    PERFORM eppm.require_permission('access.manage');
    context := eppm.current_actor();
    IF recent AND (context ->> 'now')::bigint - (context ->> 'auth_time')::bigint
        >= (context ->> 'reauthentication_seconds')::bigint THEN
        RAISE EXCEPTION 'Sign in again before changing application access' USING ERRCODE='42501';
    END IF;
    RETURN context;
END $$;

CREATE FUNCTION eppm.canonical_scope(document jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE projects jsonb := '[]'::jsonb; conditions jsonb := '[]'::jsonb;
BEGIN
    IF NOT eppm.valid_scope_structure(document) THEN
        RAISE EXCEPTION 'Invalid scope structure' USING ERRCODE='22023';
    END IF;
    IF document ->> 'kind' = 'projects' THEN projects := to_jsonb(eppm.scope_reference_ids(document -> 'project_ids')); END IF;
    IF document ->> 'kind' = 'properties' THEN
        SELECT jsonb_agg(jsonb_build_object('property_id', condition -> 'property_id',
            'operator', condition -> 'operator', 'value_ids', to_jsonb(eppm.scope_reference_ids(condition -> 'value_ids')))
            ORDER BY ordinal) INTO conditions FROM jsonb_array_elements(document -> 'conditions') WITH ORDINALITY parts(condition, ordinal);
    END IF;
    RETURN jsonb_build_object('kind', document -> 'kind', 'project_ids', projects, 'conditions', conditions);
END $$;

CREATE FUNCTION eppm.active_access_administrators() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
    SELECT count(DISTINCT u.id) FROM eppm.app_user u JOIN eppm.app_role_assignment a ON a.user_id=u.id
    WHERE u.status='active' AND a.role='access_admin' AND a.invalid_reason=''
      AND a.scope_json ->> 'kind'='all' AND eppm.valid_scope_structure(a.scope_json)
$$;

CREATE FUNCTION eppm.record_access_audit(context jsonb, target text, action text, details jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    -- Context was captured before a permitted self-disable/revocation. This
    -- private helper cannot be called with caller-supplied attribution.
    INSERT INTO eppm.app_security_audit(occurred_at,actor,target,action,outcome,correlation_id,details_json)
    VALUES ((context ->> 'now')::bigint, context ->> 'actor', target, action, 'success', context ->> 'correlation_id', details);
    UPDATE eppm.app_security_state SET revision=revision+1 WHERE id=1;
END $$;

CREATE FUNCTION eppm.admin_set_status(user_key bigint, new_status text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb; previous text;
BEGIN
    PERFORM eppm.lock_access_administration();
    context := eppm.require_access_administration(true);
    IF new_status IS NULL OR new_status NOT IN ('pending','active','disabled') THEN
        RAISE EXCEPTION 'Unknown user status' USING ERRCODE='22023';
    END IF;
    SELECT status INTO previous FROM eppm.app_user WHERE id=user_key FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501'; END IF;
    UPDATE eppm.app_user SET status=new_status,updated_at=(context ->> 'now')::bigint WHERE id=user_key;
    IF eppm.active_access_administrators()=0 THEN
        RAISE EXCEPTION 'At least one active access administrator must remain' USING ERRCODE='22023';
    END IF;
    PERFORM eppm.record_access_audit(context || jsonb_build_object('actor',context ->> 'user_id'), user_key::text,
        'user.status', jsonb_build_object('before',previous,'after',new_status));
END $$;

CREATE FUNCTION eppm.admin_grant(user_key bigint, role_code text, scope_data jsonb) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb; scope jsonb; assignment_key bigint; reason text;
BEGIN
    PERFORM eppm.lock_access_administration();
    context := eppm.require_access_administration(true);
    scope := eppm.canonical_scope(scope_data);
    IF role_code IS NULL OR NOT EXISTS (SELECT 1 FROM eppm.role_permission WHERE role=role_code)
       OR EXISTS (SELECT 1 FROM eppm.role_permission WHERE role=role_code AND application_wide AND scope ->> 'kind'<>'all') THEN
        RAISE EXCEPTION 'Invalid fixed role or application scope' USING ERRCODE='22023';
    END IF;
    PERFORM 1 FROM eppm.app_user WHERE id=user_key;
    IF NOT FOUND THEN RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501'; END IF;
    PERFORM eppm.resolve_scope(scope);
    INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
        VALUES (user_key,role_code,scope,(context ->> 'now')::bigint,context ->> 'user_id') ON CONFLICT DO NOTHING;
    SELECT id,invalid_reason INTO assignment_key,reason FROM eppm.app_role_assignment
        WHERE user_id=user_key AND role=role_code AND scope_json=scope;
    IF reason <> '' THEN RAISE EXCEPTION 'Revoke the invalid assignment before granting its replacement' USING ERRCODE='22023'; END IF;
    PERFORM eppm.record_access_audit(context || jsonb_build_object('actor',context ->> 'user_id'),user_key::text,
        'role.grant',jsonb_build_object('assignment_id',assignment_key,'role',role_code,'scope',scope));
    RETURN assignment_key;
END $$;

CREATE FUNCTION eppm.admin_revoke(assignment_key bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb; assignment eppm.app_role_assignment;
BEGIN
    PERFORM eppm.lock_access_administration();
    context := eppm.require_access_administration(true);
    SELECT * INTO assignment FROM eppm.app_role_assignment WHERE id=assignment_key FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501'; END IF;
    DELETE FROM eppm.app_role_assignment WHERE id=assignment_key;
    IF eppm.active_access_administrators()=0 THEN
        RAISE EXCEPTION 'At least one active access administrator must remain' USING ERRCODE='22023';
    END IF;
    PERFORM eppm.record_access_audit(context || jsonb_build_object('actor',context ->> 'user_id'),assignment.user_id::text,
        'role.revoke',jsonb_build_object('assignment_id',assignment.id,'role',assignment.role));
END $$;

CREATE FUNCTION eppm.admin_register(issuer text, subject text, display_label text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb; user_key bigint;
BEGIN
    PERFORM eppm.lock_access_administration();
    context := eppm.require_access_administration(true);
    IF issuer IS NULL OR length(trim(issuer))=0 OR length(issuer)>2048 OR issuer ~ '[[:cntrl:]]'
       OR subject IS NULL OR length(trim(subject))=0 OR length(subject)>512 OR subject ~ '[[:cntrl:]]'
       OR display_label IS NULL OR length(display_label)>256 OR display_label ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'Invalid identity reference' USING ERRCODE='22023';
    END IF;
    INSERT INTO eppm.app_user(display_name,created_at,updated_at)
        VALUES (display_label,(context ->> 'now')::bigint,(context ->> 'now')::bigint) RETURNING id INTO user_key;
    INSERT INTO eppm.app_identity(user_id,issuer,subject) VALUES (user_key,issuer,subject);
    PERFORM eppm.record_access_audit(context || jsonb_build_object('actor',context ->> 'user_id'),user_key::text,
        'user.register',jsonb_build_object('status','pending'));
    RETURN user_key;
END $$;

CREATE FUNCTION eppm.admin_resolve_scope(scope_data jsonb) RETURNS bigint[]
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    PERFORM eppm.require_access_administration();
    RETURN eppm.resolve_scope(eppm.canonical_scope(scope_data));
END $$;

CREATE FUNCTION eppm.admin_project_choices(search_text text) RETURNS TABLE(id bigint,name text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    PERFORM eppm.require_access_administration();
    IF search_text IS NULL OR length(search_text)>256 OR search_text ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'Invalid search text' USING ERRCODE='22023';
    END IF;
    RETURN QUERY SELECT p.id,p.name FROM eppm.project p
        WHERE position(lower(search_text) IN lower(p.name))>0 OR p.id::text=search_text ORDER BY p.id LIMIT 100;
END $$;

CREATE FUNCTION eppm.access_security_revision() RETURNS bigint
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    PERFORM eppm.current_actor(false);
    RETURN (SELECT revision FROM eppm.app_security_state WHERE id=1);
END $$;

CREATE FUNCTION eppm.admin_scope_catalog() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE result jsonb; property record; options jsonb;
BEGIN
    PERFORM eppm.require_access_administration();
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'label',name) ORDER BY id),'[]'::jsonb)
        INTO options FROM eppm.project_type;
    result := jsonb_build_array(jsonb_build_object('property_id','project_type_id','label','Project template','values',options));
    FOR property IN SELECT a.id,p.param_id,p.param_name FROM eppm.app_scope_property a
        JOIN eppm.schema_parameters p ON p.param_id=a.param_id WHERE p.param_type='ENUM' ORDER BY a.id
    LOOP
        SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'label',option_value) ORDER BY id),'[]'::jsonb)
            INTO options FROM eppm.schema_param_options WHERE param_id=property.param_id;
        result := result || jsonb_build_array(jsonb_build_object('property_id','enum:' || property.id,
            'label',property.param_name,'param_id',property.param_id,'values',options));
    END LOOP;
    RETURN result;
END $$;

CREATE FUNCTION eppm.operator_appoint_admin(user_key bigint, operator_name text, correlation text,
                                         now_seconds bigint, reason text, initial_setup boolean) RETURNS void
LANGUAGE plpgsql SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE context jsonb;
BEGIN
    -- No runtime EXECUTE grant. A deployment command supplies separate operator
    -- credentials and its explicit attribution; ordinary actors never inherit it.
    PERFORM eppm.lock_access_administration();
    IF operator_name IS NULL OR length(trim(operator_name))=0 OR length(operator_name)>256 OR operator_name ~ '[[:cntrl:]]'
       OR correlation IS NULL OR length(trim(correlation))=0 OR length(correlation)>256 OR correlation ~ '[[:cntrl:]]'
       OR reason IS NULL OR length(trim(reason))=0 OR length(reason)>1000 OR reason ~ '[[:cntrl:]]'
       OR now_seconds IS NULL OR initial_setup IS NULL THEN
        RAISE EXCEPTION 'Explicit operator context and reason are required' USING ERRCODE='22023';
    END IF;
    IF initial_setup AND ((SELECT bootstrap_complete FROM eppm.app_security_state WHERE id=1)
       OR EXISTS (SELECT 1 FROM eppm.app_role_assignment WHERE role='access_admin')) THEN
        RAISE EXCEPTION 'Initial access setup is already complete; use explicit recovery' USING ERRCODE='22023';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM eppm.app_identity WHERE user_id=user_key AND verified_at IS NOT NULL) THEN
        RAISE EXCEPTION 'Select an existing account with a verified OIDC login' USING ERRCODE='22023';
    END IF;
    UPDATE eppm.app_user SET status='active',updated_at=now_seconds WHERE id=user_key;
    INSERT INTO eppm.app_role_assignment(user_id,role,scope_json,created_at,created_by)
        VALUES (user_key,'access_admin',eppm.canonical_scope('{"kind":"all"}'),now_seconds,'operator:' || operator_name)
        ON CONFLICT DO NOTHING;
    UPDATE eppm.app_security_state SET bootstrap_complete=true WHERE id=1;
    context := jsonb_build_object('actor','operator:' || operator_name,'now',now_seconds,'correlation_id',correlation);
    PERFORM eppm.record_access_audit(context,user_key::text,
        CASE WHEN initial_setup THEN 'access.bootstrap' ELSE 'access.recover' END,jsonb_build_object('reason',reason));
END $$;

CREATE POLICY account_read ON eppm.app_user FOR SELECT TO eppm_runtime
    USING (id=(SELECT (eppm.current_actor(false) ->> 'user_id')::bigint) OR (SELECT eppm.is_access_administrator()));
CREATE POLICY assignment_read ON eppm.app_role_assignment FOR SELECT TO eppm_runtime
    USING ((SELECT eppm.is_access_administrator()) OR (
        user_id=(SELECT (eppm.current_actor(false) ->> 'user_id')::bigint)
        AND (SELECT eppm.current_actor(false) ->> 'status'='active')));
CREATE POLICY audit_read ON eppm.app_security_audit FOR SELECT TO eppm_runtime USING ((SELECT eppm.is_access_administrator()));
GRANT SELECT ON eppm.app_user,eppm.app_role_assignment,eppm.app_security_audit TO eppm_runtime;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA eppm FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.is_access_administrator(),eppm.admin_set_status(bigint,text),
    eppm.admin_grant(bigint,text,jsonb),eppm.admin_revoke(bigint),eppm.admin_register(text,text,text),
    eppm.admin_resolve_scope(jsonb),eppm.admin_project_choices(text),eppm.access_security_revision(),
    eppm.admin_scope_catalog() TO eppm_runtime;
