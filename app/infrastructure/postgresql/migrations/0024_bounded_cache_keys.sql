-- Preserve existing cache fingerprints while expanding dependency/demand sources
-- only for selected entities. Scope membership and missing-revision checks remain
-- complete; ordinary callers still cannot invoke this private helper directly.
CREATE OR REPLACE FUNCTION eppm.current_cache_keys(kind text, selected_ids bigint[])
RETURNS TABLE(entity_id bigint, source_token text, entity_name text)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, eppm, pg_temp
SET plan_cache_mode = force_custom_plan AS $$
DECLARE actor jsonb; access_token text; visible bigint[];
BEGIN
    IF kind IS NULL OR kind NOT IN ('capacity','planning') THEN
        RAISE EXCEPTION 'Unknown cache kind' USING ERRCODE='22023';
    END IF;
    IF NOT eppm.has_business_read() THEN
        RAISE EXCEPTION 'Application access denied' USING ERRCODE='42501';
    END IF;
    actor := eppm.current_actor();
    visible := eppm.permission_projects('project.read');
    IF EXISTS(SELECT 1 FROM eppm.project project LEFT JOIN eppm.project_cache_revision r ON r.project_id=project.id
              WHERE project.id=ANY(visible) AND r.project_id IS NULL)
       OR EXISTS(SELECT 1 FROM eppm.resource_pool pool LEFT JOIN eppm.pool_cache_revision r ON r.pool_id=pool.id
                 WHERE r.pool_id IS NULL) THEN
        RAISE EXCEPTION 'Cache revision unavailable' USING ERRCODE='55000';
    END IF;
    -- permission_projects returns sorted, distinct, existing project IDs. Reuse
    -- that canonical membership after verifying its required revision rows.
    SELECT encode(eppm_crypto.digest(convert_to(jsonb_build_array(
        jsonb_build_array(identity.epoch,(SELECT oid FROM pg_database WHERE datname=current_database()),
                         actor->'user_id',actor->'session_hash'),
        catalog.revision,security.revision,to_jsonb(visible)
    )::text,'UTF8'),'sha256'),'hex') INTO access_token
    FROM eppm.database_identity identity CROSS JOIN eppm.catalog_cache_revision catalog
        CROSS JOIN eppm.app_security_state security WHERE identity.singleton AND catalog.singleton AND security.id=1;
    IF access_token IS NULL THEN
        RAISE EXCEPTION 'Cache revision unavailable' USING ERRCODE='55000';
    END IF;
    RETURN QUERY
    WITH entities AS MATERIALIZED (
        SELECT r.pool_id AS id,jsonb_build_array(r.pool_id,r.generation,r.revision) AS version,pool.name
        FROM eppm.pool_cache_revision r JOIN eppm.resource_pool pool ON pool.id=r.pool_id
        WHERE kind='capacity' AND (selected_ids IS NULL OR r.pool_id=ANY(selected_ids))
        UNION ALL
        SELECT r.project_id,jsonb_build_array(r.project_id,r.generation,r.revision),project.name
        FROM eppm.project_cache_revision r JOIN eppm.project project ON project.id=r.project_id
        WHERE kind='planning' AND r.project_id=ANY(visible)
            AND (selected_ids IS NULL OR r.project_id=ANY(selected_ids))
    ), sources AS (
        SELECT entity.id,coalesce(pred.project_id,dependency.predecessor_project_id) AS project_id
        FROM entities entity JOIN eppm.project_task task ON task.project_id=entity.id
        JOIN eppm.task_dependencies dependency ON dependency.task_id=task.id
        LEFT JOIN eppm.project_task pred ON pred.id=dependency.predecessor_task_id
        WHERE kind='planning'
            AND (dependency.predecessor_task_id IS NULL OR pred.project_id=ANY(visible))
            AND (dependency.predecessor_project_id IS NULL OR dependency.predecessor_project_id=ANY(visible))
            AND coalesce(pred.project_id,dependency.predecessor_project_id)<>entity.id
        UNION
        SELECT entity.id,pred.project_id
        FROM entities entity JOIN eppm.project_task task ON task.project_id=entity.id
        JOIN eppm.project_task pred ON pred.id=task.predecessor_id
        WHERE kind='planning' AND pred.project_id=ANY(visible) AND pred.project_id<>entity.id
        UNION
        SELECT entity.id,assignment.project_id
        FROM entities entity JOIN eppm.resource_pool_assignment assignment ON assignment.pool_id=entity.id
        WHERE kind='capacity' AND assignment.project_id=ANY(visible)
    ), source_versions AS (
        SELECT source.id,jsonb_agg(jsonb_build_array(r.project_id,r.generation,r.revision)
                                  ORDER BY r.project_id) AS versions
        FROM sources source JOIN eppm.project_cache_revision r ON r.project_id=source.project_id
        GROUP BY source.id
    )
    SELECT entity.id,encode(eppm_crypto.digest(convert_to(
        jsonb_build_array(access_token,entity.version,coalesce(sources.versions,'[]'::jsonb))::text,'UTF8'),'sha256'),'hex'),entity.name
    FROM entities entity LEFT JOIN source_versions sources ON sources.id=entity.id;
END $$;
REVOKE ALL ON FUNCTION eppm.current_cache_keys(text,bigint[]) FROM PUBLIC,eppm_runtime;
