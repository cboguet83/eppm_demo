-- Derived-data revisions, not planning versions or stale-form protection.
-- Ordinary project/assignment writes never touch a shared revision row.
CREATE TABLE eppm.project_cache_revision (
    project_id bigint PRIMARY KEY REFERENCES eppm.project(id) ON DELETE CASCADE,
    generation uuid NOT NULL DEFAULT gen_random_uuid(),
    revision bigint NOT NULL DEFAULT 0
);
CREATE TABLE eppm.pool_cache_revision (
    pool_id bigint PRIMARY KEY REFERENCES eppm.resource_pool(id) ON DELETE CASCADE,
    generation uuid NOT NULL DEFAULT gen_random_uuid(),
    revision bigint NOT NULL DEFAULT 0
);
CREATE TABLE eppm.catalog_cache_revision (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    revision bigint NOT NULL DEFAULT 0
);
INSERT INTO eppm.project_cache_revision(project_id) SELECT id FROM eppm.project;
INSERT INTO eppm.pool_cache_revision(pool_id) SELECT id FROM eppm.resource_pool;
INSERT INTO eppm.catalog_cache_revision DEFAULT VALUES;
REVOKE ALL ON eppm.project_cache_revision,eppm.pool_cache_revision,eppm.catalog_cache_revision FROM PUBLIC,eppm_runtime;

CREATE FUNCTION eppm.bump_project_cache_revisions(owners bigint[]) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
    INSERT INTO eppm.project_cache_revision(project_id,revision)
        SELECT id,1 FROM eppm.project WHERE id=ANY(owners) ORDER BY id
    ON CONFLICT(project_id) DO UPDATE SET revision=eppm.project_cache_revision.revision+1
$$;
REVOKE ALL ON FUNCTION eppm.bump_project_cache_revisions(bigint[]) FROM PUBLIC,eppm_runtime;

CREATE FUNCTION eppm.invalidate_business_caches() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE
    previous jsonb := CASE WHEN TG_OP='INSERT' THEN '{}'::jsonb ELSE to_jsonb(OLD) END;
    current_row jsonb := CASE WHEN TG_OP='DELETE' THEN '{}'::jsonb ELSE to_jsonb(NEW) END;
    owners bigint[];
BEGIN
    IF TG_ARGV[0]='catalog' THEN
        UPDATE eppm.catalog_cache_revision SET revision=revision+1 WHERE singleton;
        IF NOT FOUND THEN RAISE EXCEPTION 'Cache revision unavailable' USING ERRCODE='55000'; END IF;
    ELSIF TG_ARGV[0]='pool' THEN
        owners := CASE WHEN TG_TABLE_NAME='resource_pool'
            THEN ARRAY[(previous->>'id')::bigint,(current_row->>'id')::bigint]
            ELSE ARRAY[(previous->>'pool_id')::bigint,(current_row->>'pool_id')::bigint] END;
        INSERT INTO eppm.pool_cache_revision(pool_id,revision)
            SELECT id,1 FROM eppm.resource_pool WHERE id=ANY(owners) ORDER BY id
        ON CONFLICT(pool_id) DO UPDATE SET revision=eppm.pool_cache_revision.revision+1;
    ELSE
        IF TG_TABLE_NAME='project' THEN
            owners := ARRAY[(previous->>'id')::bigint,(current_row->>'id')::bigint];
        ELSIF TG_TABLE_NAME IN ('task_dependencies','task_tag') THEN
            SELECT array_agg(project_id) INTO owners FROM eppm.project_task
                WHERE id=ANY(ARRAY[(previous->>'task_id')::bigint,(current_row->>'task_id')::bigint]);
        ELSE
            owners := ARRAY[(previous->>'project_id')::bigint,(current_row->>'project_id')::bigint];
        END IF;
        PERFORM eppm.bump_project_cache_revisions(owners);
    END IF;
    RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION eppm.invalidate_business_caches() FROM PUBLIC,eppm_runtime;

DO $$
DECLARE
    target text;
    category text;
BEGIN
    FOR target,category IN
        SELECT name,'project' FROM unnest(ARRAY[
            'project','project_task','task_dependencies','task_tag','project_tag','project_contact','project_link',
            'project_log_event','project_property_value','project_property_value_item','project_wbs','resource_pool_assignment'
        ]) name
        UNION ALL SELECT name,'pool' FROM unnest(ARRAY['resource_pool','resource_pool_mapping','resource_pool_tag']) name
        UNION ALL SELECT name,'catalog' FROM unnest(ARRAY[
            'hierarchy_type','hierarchy_type_translation','wbs','employee','employee_calendar_exception','function','function_type',
            'project_event_type','project_event_type_translation','project_role','project_role_translation','project_type',
            'project_type_property','project_type_property_default','project_type_property_default_item','project_type_property_rule',
            'resource_pool_group','resource_pool_group_member','schema_groups','schema_param_options','schema_parameter_translation',
            'schema_parameters','tag_dictionnary','tag_group','team','team_function'
        ]) name
    LOOP
        EXECUTE format('CREATE TRIGGER cache_revision AFTER INSERT OR UPDATE OR DELETE ON eppm.%I '
                       'FOR EACH ROW EXECUTE FUNCTION eppm.invalidate_business_caches(%L)',target,category);
    END LOOP;
END $$;

-- Read effective membership and all revisions in this one statement snapshot.
-- Pool demand sources include only visible consuming project owners. A hidden
-- assignment edit cannot alter a restricted reader's pool fingerprint.
CREATE FUNCTION eppm.display_cache_revisions() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, eppm, pg_temp AS $$
DECLARE
    visible bigint[];
    result jsonb;
BEGIN
    IF NOT eppm.has_business_read() THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    visible := eppm.permission_projects('project.read');
    IF EXISTS(SELECT 1 FROM eppm.project project LEFT JOIN eppm.project_cache_revision r ON r.project_id=project.id
              WHERE project.id=ANY(visible) AND r.project_id IS NULL)
       OR EXISTS(SELECT 1 FROM eppm.resource_pool pool LEFT JOIN eppm.pool_cache_revision r ON r.pool_id=pool.id
                 WHERE r.pool_id IS NULL) THEN
        RAISE EXCEPTION 'Cache revision unavailable' USING ERRCODE='55000';
    END IF;
    WITH dependency_sources AS (
        SELECT task.project_id,coalesce(pred.project_id,dependency.predecessor_project_id) AS source_id
        FROM eppm.task_dependencies dependency JOIN eppm.project_task task ON task.id=dependency.task_id
        LEFT JOIN eppm.project_task pred ON pred.id=dependency.predecessor_task_id
        WHERE task.project_id=ANY(visible)
          AND (dependency.predecessor_task_id IS NULL OR pred.project_id=ANY(visible))
          AND (dependency.predecessor_project_id IS NULL OR dependency.predecessor_project_id=ANY(visible))
        UNION SELECT task.project_id,pred.project_id FROM eppm.project_task task
            JOIN eppm.project_task pred ON pred.id=task.predecessor_id
            WHERE task.project_id=ANY(visible) AND pred.project_id=ANY(visible)
    ), dependency_sets AS (
        SELECT project_id,jsonb_agg(source_id ORDER BY source_id) AS sources
        FROM dependency_sources WHERE source_id<>project_id GROUP BY project_id
    ), pool_sources AS (
        SELECT pool_id,jsonb_agg(project_id ORDER BY project_id) AS sources FROM
            (SELECT DISTINCT pool_id,project_id FROM eppm.resource_pool_assignment WHERE project_id=ANY(visible)) assignments
        GROUP BY pool_id
    )
    SELECT jsonb_build_object(
        'epoch',identity.epoch,'database_oid',(SELECT oid FROM pg_database WHERE datname=current_database()),
        'catalog',catalog.revision,'security',security.revision,
        'projects',coalesce((SELECT jsonb_agg(jsonb_build_array(r.project_id,r.generation,r.revision,
            coalesce(d.sources,'[]'::jsonb)) ORDER BY r.project_id)
            FROM eppm.project_cache_revision r LEFT JOIN dependency_sets d ON d.project_id=r.project_id
            WHERE r.project_id=ANY(visible)),'[]'::jsonb),
        'pools',coalesce((SELECT jsonb_agg(jsonb_build_array(r.pool_id,r.generation,r.revision,pool.name,
            coalesce(sources.sources,'[]'::jsonb)) ORDER BY r.pool_id)
            FROM eppm.pool_cache_revision r JOIN eppm.resource_pool pool ON pool.id=r.pool_id
            LEFT JOIN pool_sources sources ON sources.pool_id=r.pool_id),'[]'::jsonb)
    ) INTO result FROM eppm.database_identity identity CROSS JOIN eppm.catalog_cache_revision catalog
        CROSS JOIN eppm.app_security_state security WHERE identity.singleton AND catalog.singleton AND security.id=1;
    IF result IS NULL THEN RAISE EXCEPTION 'Cache revision unavailable' USING ERRCODE='55000'; END IF;
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION eppm.display_cache_revisions() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.display_cache_revisions() TO eppm_runtime;
