-- Permanent business visibility, old/new owner guards and protected-change audit.
SET LOCAL search_path = pg_catalog, eppm, pg_temp;

CREATE OR REPLACE FUNCTION eppm.permission_projects(requested_permission text) RETURNS bigint[]
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE scope jsonb; selected bigint[] := ARRAY[]::bigint[];
BEGIN
    -- Application-wide capabilities (notably finance) do not grant portfolio
    -- visibility. Never turn their all-scope marker into a project-ID directory.
    IF requested_permission NOT IN ('project.read','project.edit','project.approve') THEN
        PERFORM eppm.current_actor();
        RETURN selected;
    END IF;
    FOR scope IN SELECT eppm.permission_scopes(requested_permission) LOOP
        BEGIN
            IF scope ->> 'kind' = 'all' THEN RETURN eppm.resolve_scope(scope); END IF;
            selected := selected || eppm.resolve_scope(scope);
        EXCEPTION WHEN invalid_parameter_value THEN CONTINUE;
        END;
    END LOOP;
    RETURN ARRAY(SELECT DISTINCT value FROM unnest(selected) value ORDER BY value);
END $$;

CREATE FUNCTION eppm.runtime_session() RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, eppm, pg_temp AS $$
    SELECT NOT r.rolsuper AND pg_has_role(session_user, 'eppm_runtime', 'MEMBER')
    FROM pg_catalog.pg_roles r WHERE r.rolname = session_user
$$;

CREATE FUNCTION eppm.require_permission(requested_permission text, owners bigint[] DEFAULT NULL) RETURNS void
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    IF eppm.has_global_permission(requested_permission) THEN RETURN; END IF;
    IF owners IS NOT NULL AND cardinality(owners) > 0
       AND array_position(owners, NULL) IS NULL
       AND owners <@ eppm.permission_projects(requested_permission) THEN RETURN; END IF;
    RAISE EXCEPTION 'Application access denied' USING ERRCODE = '42501';
END $$;

CREATE FUNCTION eppm.task_owner(task_key bigint) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
    SELECT project_id FROM eppm.project_task WHERE id = task_key
$$;

CREATE FUNCTION eppm.business_owners(target text, row_data jsonb) RETURNS bigint[]
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE owners bigint[];
BEGIN
    IF row_data IS NULL OR row_data = '{}'::jsonb THEN RETURN ARRAY[]::bigint[]; END IF;
    IF target = 'project' THEN RETURN ARRAY[(row_data ->> 'id')::bigint]; END IF;
    IF target IN ('task_tag', 'task_dependencies') THEN
        owners := ARRAY[eppm.task_owner((row_data ->> 'task_id')::bigint)];
        IF target = 'task_dependencies' THEN
            IF row_data ->> 'predecessor_task_id' IS NOT NULL THEN
                owners := owners || eppm.task_owner((row_data ->> 'predecessor_task_id')::bigint);
            END IF;
            IF row_data ->> 'predecessor_project_id' IS NOT NULL THEN
                owners := owners || (row_data ->> 'predecessor_project_id')::bigint;
            END IF;
        END IF;
        RETURN owners;
    END IF;
    owners := ARRAY[(row_data ->> 'project_id')::bigint];
    IF target = 'resource_pool_assignment' AND row_data ->> 'task_id' IS NOT NULL
       AND eppm.task_owner((row_data ->> 'task_id')::bigint) IS DISTINCT FROM owners[1] THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE = '42501';
    END IF;
    RETURN owners;
END $$;

CREATE FUNCTION eppm.protected_business_change(target text, before_row jsonb, after_row jsonb) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
BEGIN
    IF before_row = after_row THEN RETURN false; END IF;
    IF target = 'project' THEN
        RETURN before_row -> 'project_type_id' IS DISTINCT FROM after_row -> 'project_type_id';
    END IF;
    IF target IN ('schema_parameters', 'schema_param_options', 'project_type', 'project_type_property',
                  'project_type_property_rule', 'project_type_property_default', 'project_type_property_default_item') THEN
        RETURN true;
    END IF;
    RETURN target IN ('project_property_value', 'project_property_value_item') AND EXISTS (
        SELECT 1 FROM eppm.schema_parameters WHERE param_type = 'ENUM'
        AND param_id IN (before_row ->> 'param_id', after_row ->> 'param_id')
    );
END $$;

CREATE FUNCTION eppm.guard_business_write() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE before_row jsonb := coalesce(to_jsonb(OLD), '{}'::jsonb);
        after_row jsonb := coalesce(to_jsonb(NEW), '{}'::jsonb);
        key_name text; predicate text; required text;
BEGIN
    IF NOT eppm.runtime_session() THEN RETURN coalesce(NEW, OLD); END IF;
    PERFORM eppm.current_actor();
    IF TG_ARGV[0] = 'shared' THEN
        PERFORM eppm.require_permission('business.manage');
        RETURN coalesce(NEW, OLD);
    END IF;
    IF TG_ARGV[0] = 'finance' THEN
        PERFORM eppm.require_permission('finance.edit');
        IF TG_TABLE_NAME = 'finance_snapshot' AND TG_OP = 'INSERT' THEN
            NEW.author := eppm.current_actor() ->> 'user_id';
            NEW.created_at := (eppm.current_actor() ->> 'now')::bigint;
        ELSIF TG_TABLE_NAME = 'finance_snapshot' AND TG_OP = 'UPDATE' THEN
            NEW.author := OLD.author;
            NEW.created_at := OLD.created_at;
        ELSIF TG_TABLE_NAME = 'finance_cancellation' AND TG_OP = 'INSERT' THEN
            NEW.author := eppm.current_actor() ->> 'user_id';
            NEW.occurred_at := (eppm.current_actor() ->> 'now')::bigint;
        END IF;
        RETURN coalesce(NEW, OLD);
    END IF;
    IF TG_OP = 'INSERT' THEN
        -- Inspect an existing conflict target before any ON CONFLICT action.
        -- Identifiers come only from the installed trigger and native PK catalog.
        SELECT string_agg(format('%I IS NOT DISTINCT FROM ($1).%I', a.attname, a.attname), ' AND ')
            INTO predicate FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = TG_RELID AND i.indisprimary;
        EXECUTE format('SELECT to_jsonb(existing) FROM eppm.%I existing WHERE %s', TG_TABLE_NAME, predicate)
            INTO before_row USING NEW;
        before_row := coalesce(before_row, '{}'::jsonb);
    END IF;
    IF TG_TABLE_NAME = 'project' AND TG_OP = 'INSERT' THEN
        PERFORM eppm.require_permission('project.create');
    ELSE
        required := CASE WHEN TG_TABLE_NAME = 'project' AND TG_OP = 'DELETE' THEN 'project.delete' ELSE 'project.edit' END;
        PERFORM eppm.require_permission(required,
            eppm.business_owners(TG_TABLE_NAME, before_row) || eppm.business_owners(TG_TABLE_NAME, after_row));
        IF TG_TABLE_NAME = 'project_task'
           AND before_row -> 'predecessor_id' IS DISTINCT FROM after_row -> 'predecessor_id' THEN
            FOREACH key_name IN ARRAY ARRAY['before', 'after'] LOOP
                IF (CASE key_name WHEN 'before' THEN before_row ELSE after_row END) ->> 'predecessor_id' IS NOT NULL THEN
                    PERFORM eppm.require_permission('project.edit', ARRAY[eppm.task_owner(
                        ((CASE key_name WHEN 'before' THEN before_row ELSE after_row END) ->> 'predecessor_id')::bigint)]);
                END IF;
            END LOOP;
        END IF;
        IF eppm.protected_business_change(TG_TABLE_NAME, before_row, after_row) THEN
            PERFORM eppm.require_permission('project.protected_properties');
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'project_task' AND TG_OP = 'DELETE' THEN
        -- Authorize dependent tag deletion while its owner still exists. The
        -- native FK cascade then finds no tags; no request-local bypass is used.
        DELETE FROM eppm.task_tag WHERE task_id = OLD.id;
        DELETE FROM eppm.resource_pool_assignment WHERE task_id = OLD.id;
    END IF;
    RETURN coalesce(NEW, OLD);
END $$;

CREATE FUNCTION eppm.audit_business_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE before_row jsonb := coalesce(to_jsonb(OLD), '{}'::jsonb);
        after_row jsonb := coalesce(to_jsonb(NEW), '{}'::jsonb);
        context jsonb; changed_fields jsonb; changes jsonb; details jsonb; row_data jsonb;
BEGIN
    IF NOT eppm.runtime_session() OR NOT eppm.protected_business_change(TG_TABLE_NAME, before_row, after_row) THEN
        RETURN NULL;
    END IF;
    context := eppm.current_actor();
    SELECT coalesce(jsonb_agg(name ORDER BY name), '[]'::jsonb),
           coalesce(jsonb_object_agg(name, jsonb_build_object('before', before_row -> name, 'after', after_row -> name))
               FILTER (WHERE name IN ('project_type_id','param_id','param_type','kind','text_value','value','option_value')), '{}'::jsonb)
        INTO changed_fields, changes FROM (
            SELECT jsonb_object_keys(before_row || after_row) AS name
        ) fields WHERE before_row -> name IS DISTINCT FROM after_row -> name;
    row_data := CASE TG_OP WHEN 'DELETE' THEN before_row ELSE after_row END;
    details := jsonb_build_object('table', TG_TABLE_NAME, 'operation', TG_OP, 'fields', changed_fields, 'changes', changes);
    IF row_data ->> 'param_id' IS NOT NULL THEN details := details || jsonb_build_object('property', row_data ->> 'param_id'); END IF;
    INSERT INTO eppm.app_security_audit(occurred_at,actor,target,action,outcome,correlation_id,details_json)
    VALUES ((context ->> 'now')::bigint, context ->> 'user_id',
            coalesce(row_data ->> 'project_id', row_data ->> 'id', 'definition'),
            'project.protected_property_change', 'success', context ->> 'correlation_id', details);
    RETURN NULL;
END $$;

DO $$
DECLARE target text; read_predicate text; category text; sequence_name text;
BEGIN
    -- All existing tables start with RLS. Missing policies remain default-deny.
    FOR target IN SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'eppm'
        AND tablename NOT IN ('schema_migration','database_identity')
    LOOP EXECUTE format('ALTER TABLE eppm.%I ENABLE ROW LEVEL SECURITY', target); END LOOP;

    FOREACH target IN ARRAY ARRAY[
        'hierarchy_type','hierarchy_type_translation','wbs','schema_groups','schema_parameters',
        'schema_param_options','schema_parameter_translation','project_type','project_type_property',
        'project_type_property_rule','project_type_property_default','project_type_property_default_item',
        'function_type','function','team','employee','employee_calendar_exception','team_function',
        'resource_pool','resource_pool_mapping','resource_pool_tag','resource_pool_group','resource_pool_group_member',
        'tag_group','tag_dictionnary','project_role','project_role_translation','project_event_type','project_event_type_translation',
        'project','project_task','project_wbs','project_link','project_contact','project_log_event',
        'project_property_value','project_property_value_item','project_tag','task_tag','task_dependencies','resource_pool_assignment',
        'finance_snapshot','finance_row','finance_amount','finance_cancellation'
    ] LOOP
        IF target IN ('finance_snapshot','finance_row','finance_amount','finance_cancellation') THEN
            category := 'finance';
            read_predicate := '(SELECT eppm.current_actor()) IS NOT NULL';
        ELSIF target = 'project' THEN
            category := 'owned';
            read_predicate := 'id IN (SELECT unnest(eppm.permission_projects(''project.read'')))';
        ELSIF target IN ('project_task','project_wbs','project_link','project_contact','project_log_event',
                        'project_property_value','project_property_value_item','project_tag','resource_pool_assignment') THEN
            category := 'owned';
            read_predicate := 'project_id IN (SELECT unnest(eppm.permission_projects(''project.read'')))';
        ELSIF target IN ('task_tag','task_dependencies') THEN
            category := 'owned';
            read_predicate := 'task_id IN (SELECT id FROM eppm.project_task)';
            IF target = 'task_dependencies' THEN
                read_predicate := read_predicate || ' AND (predecessor_task_id IS NULL OR predecessor_task_id IN (SELECT id FROM eppm.project_task))'
                    || ' AND (predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))';
            END IF;
        ELSE
            category := 'shared';
            read_predicate := CASE WHEN target IN ('employee','employee_calendar_exception')
                THEN '(SELECT eppm.has_global_permission(''business.manage''))'
                WHEN target = 'wbs' THEN '(SELECT eppm.current_actor()) IS NOT NULL'
                ELSE '(SELECT eppm.has_business_read())' END;
        END IF;
        EXECUTE format('CREATE POLICY business_select ON eppm.%I FOR SELECT TO eppm_runtime USING (%s)', target, read_predicate);
        -- Guards validate old/new ownership for every selected row and before
        -- conflict handling. RLS still prevents targeting unreadable rows.
        EXECUTE format('CREATE POLICY business_insert ON eppm.%I FOR INSERT TO eppm_runtime WITH CHECK (true)', target);
        EXECUTE format('CREATE POLICY business_update ON eppm.%I FOR UPDATE TO eppm_runtime USING (%s) WITH CHECK (true)', target, read_predicate);
        EXECUTE format('CREATE POLICY business_delete ON eppm.%I FOR DELETE TO eppm_runtime USING (%s)', target, read_predicate);
        EXECUTE format('CREATE TRIGGER authorize_business BEFORE INSERT OR UPDATE OR DELETE ON eppm.%I
            FOR EACH ROW EXECUTE FUNCTION eppm.guard_business_write(%L)', target, category);
        EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON eppm.%I TO eppm_runtime', target);
        FOR sequence_name IN SELECT pg_get_serial_sequence(format('eppm.%I', target), a.attname)
            FROM pg_catalog.pg_attribute a WHERE a.attrelid = format('eppm.%I', target)::regclass AND a.attidentity <> ''
        LOOP EXECUTE format('GRANT USAGE ON SEQUENCE %s TO eppm_runtime', sequence_name); END LOOP;
    END LOOP;

    FOREACH target IN ARRAY ARRAY['schema_parameters','schema_param_options','project_type','project_type_property',
        'project_type_property_rule','project_type_property_default','project_type_property_default_item',
        'project','project_property_value','project_property_value_item']
    LOOP
        EXECUTE format('CREATE TRIGGER audit_business AFTER INSERT OR UPDATE OR DELETE ON eppm.%I
            FOR EACH ROW EXECUTE FUNCTION eppm.audit_business_change()', target);
    END LOOP;
END $$;

-- Hide the legacy predecessor column even when its task row is visible. The
-- permanent projection explicitly applies scope before masking its endpoint.
REVOKE SELECT ON eppm.project_task FROM eppm_runtime;
GRANT SELECT(id,project_id,task_name,phase,start_date,end_date,progress_pct,description) ON eppm.project_task TO eppm_runtime;
CREATE VIEW eppm.visible_project_task WITH (security_barrier = true) AS
    SELECT task.id,task.project_id,task.task_name,task.phase,task.start_date,task.end_date,task.progress_pct,task.description,
        CASE WHEN EXISTS (SELECT 1 FROM eppm.project_task predecessor WHERE predecessor.id=task.predecessor_id
            AND predecessor.project_id IN (SELECT unnest(eppm.permission_projects('project.read'))))
        THEN task.predecessor_id ELSE NULL END AS predecessor_id
    FROM eppm.project_task task WHERE task.project_id IN (SELECT unnest(eppm.permission_projects('project.read')));
GRANT SELECT ON eppm.visible_project_task TO eppm_runtime;

-- Portfolio manager labels are an existing public business projection. Raw
-- employee contact/staffing data stays accessible only to organization admins.
CREATE VIEW eppm.project_manager_directory WITH (security_barrier = true) AS
    SELECT f.function_id, coalesce((SELECT nullif(trim(e.firstname || ' ' || e.lastname),'')
        FROM eppm.employee e WHERE e.function_id=f.function_id AND trim(e.firstname || e.lastname)<>''
        ORDER BY e.lastname,e.firstname,e.employee_id LIMIT 1),nullif(f.name,''),'—') AS label
    FROM eppm.function f WHERE (SELECT eppm.has_business_read());
GRANT SELECT ON eppm.project_manager_directory TO eppm_runtime;

-- Scope reference identifiers are catalog metadata, never arbitrary project sets.
CREATE POLICY scope_catalog_read ON eppm.app_scope_property FOR SELECT TO eppm_runtime
    USING ((SELECT eppm.has_business_read()) OR (SELECT eppm.has_global_permission('access.manage')));
GRANT SELECT ON eppm.app_scope_property TO eppm_runtime;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA eppm FROM PUBLIC;
