-- Project-level links expose pool labels, while task-level allocations also
-- expose capacity warnings. Only the latter depend on other visible consumers.
CREATE OR REPLACE FUNCTION eppm.planning_task_source_keys(selected_ids bigint[])
RETURNS TABLE(project_id bigint, source_token text)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, eppm, pg_temp
SET plan_cache_mode = force_custom_plan AS $$
BEGIN
    IF selected_ids IS NULL OR cardinality(selected_ids) NOT BETWEEN 1 AND 25
       OR array_position(selected_ids,NULL) IS NOT NULL THEN
        RAISE EXCEPTION 'Invalid task batch' USING ERRCODE='22023';
    END IF;
    RETURN QUERY
    WITH projects AS MATERIALIZED (
        SELECT entity_id,source.source_token FROM eppm.current_cache_keys('planning',selected_ids) source
    ), assignments AS MATERIALIZED (
        SELECT assignment.project_id,assignment.pool_id,bool_or(assignment.task_id IS NOT NULL) AS has_tasks
        FROM eppm.resource_pool_assignment assignment JOIN projects ON projects.entity_id=assignment.project_id
        GROUP BY assignment.project_id,assignment.pool_id
    ), pools AS MATERIALIZED (
        SELECT entity_id,source.source_token FROM eppm.current_cache_keys(
            'capacity',ARRAY(SELECT DISTINCT pool_id FROM assignments WHERE has_tasks)) source
    ), pool_sources AS (
        SELECT assignment.project_id,jsonb_agg(jsonb_build_array(assignment.pool_id,
            CASE WHEN assignment.has_tasks THEN pools.source_token ELSE
                encode(eppm_crypto.digest(convert_to(jsonb_build_array('planning.pool.v1',
                    jsonb_build_array(r.pool_id,r.generation,r.revision))::text,'UTF8'),'sha256'),'hex') END
            ) ORDER BY assignment.pool_id) AS sources
        FROM assignments assignment JOIN eppm.pool_cache_revision r ON r.pool_id=assignment.pool_id
        LEFT JOIN pools ON pools.entity_id=assignment.pool_id GROUP BY assignment.project_id
    )
    SELECT projects.entity_id,encode(eppm_crypto.digest(convert_to(jsonb_build_array(
        'planning.tasks.v2',projects.source_token,coalesce(pool_sources.sources,'[]'::jsonb)
    )::text,'UTF8'),'sha256'),'hex')
    FROM projects LEFT JOIN pool_sources ON pool_sources.project_id=projects.entity_id;
END $$;
REVOKE ALL ON FUNCTION eppm.planning_task_source_keys(bigint[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.planning_task_source_keys(bigint[]) TO eppm_runtime;
