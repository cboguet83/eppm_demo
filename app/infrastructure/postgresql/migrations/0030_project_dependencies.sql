-- Project-owned incoming links. Scheduling calculations remain in Python.
CREATE TABLE eppm.project_dependency (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id bigint NOT NULL REFERENCES eppm.project(id) ON DELETE CASCADE,
    predecessor_project_id bigint REFERENCES eppm.project(id) ON DELETE CASCADE,
    predecessor_task_id bigint REFERENCES eppm.project_task(id) ON DELETE CASCADE,
    link_type text NOT NULL DEFAULT 'FS' CHECK (link_type IN ('FS','FF','SS','SF')),
    lag_days integer NOT NULL DEFAULT 0,
    CHECK ((predecessor_project_id IS NULL) <> (predecessor_task_id IS NULL)),
    CHECK (predecessor_project_id IS NULL OR predecessor_project_id <> project_id)
);
CREATE INDEX project_dependency_owner ON eppm.project_dependency(project_id,id);
CREATE INDEX project_dependency_project ON eppm.project_dependency(predecessor_project_id);
CREATE INDEX project_dependency_task ON eppm.project_dependency(predecessor_task_id);
ALTER TABLE eppm.project_dependency ENABLE ROW LEVEL SECURITY;
ALTER TABLE eppm.project_dependency FORCE ROW LEVEL SECURITY;
CREATE POLICY business_select ON eppm.project_dependency FOR SELECT TO eppm_runtime USING (
    project_id IN (SELECT id FROM eppm.project)
    AND (predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))
    AND (predecessor_task_id IS NULL OR predecessor_task_id IN (SELECT id FROM eppm.project_task))
);
CREATE POLICY business_insert ON eppm.project_dependency FOR INSERT TO eppm_runtime WITH CHECK (true);
CREATE POLICY business_update ON eppm.project_dependency FOR UPDATE TO eppm_runtime USING (
    project_id IN (SELECT id FROM eppm.project)
    AND (predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))
    AND (predecessor_task_id IS NULL OR predecessor_task_id IN (SELECT id FROM eppm.project_task))
) WITH CHECK (true);
CREATE POLICY business_delete ON eppm.project_dependency FOR DELETE TO eppm_runtime USING (
    project_id IN (SELECT id FROM eppm.project)
    AND (predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))
    AND (predecessor_task_id IS NULL OR predecessor_task_id IN (SELECT id FROM eppm.project_task))
);

CREATE FUNCTION eppm.guard_project_dependency() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,eppm,pg_temp AS $$
DECLARE selected eppm.project_dependency; prior eppm.project_dependency; owner bigint;
BEGIN
    selected := CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
    IF selected.predecessor_task_id IS NOT NULL THEN
        owner := eppm.task_owner(selected.predecessor_task_id);
        IF owner = selected.project_id THEN
            RAISE EXCEPTION 'A project cannot depend on its own step' USING ERRCODE='23514';
        END IF;
    ELSE owner := selected.predecessor_project_id;
    END IF;
    IF NOT eppm.runtime_session() THEN RETURN selected; END IF;
    PERFORM eppm.current_actor();
    -- A missing FK owner can occur only during its native, already-authorized
    -- parent deletion. No request flag or trigger-depth bypass is accepted.
    IF TG_OP='DELETE' AND (
        NOT EXISTS(SELECT 1 FROM eppm.project WHERE id=OLD.project_id)
        OR (OLD.predecessor_project_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM eppm.project WHERE id=OLD.predecessor_project_id))
        OR (OLD.predecessor_task_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM eppm.project_task WHERE id=OLD.predecessor_task_id))
    ) THEN RETURN OLD; END IF;
    IF TG_OP='INSERT' THEN SELECT * INTO prior FROM eppm.project_dependency WHERE id=NEW.id;
    ELSE prior := OLD;
    END IF;
    IF prior.id IS NOT NULL THEN
        PERFORM eppm.require_permission('project.edit',ARRAY[prior.project_id]);
        PERFORM eppm.require_permission('project.read',ARRAY[coalesce(prior.predecessor_project_id,eppm.task_owner(prior.predecessor_task_id))]);
    END IF;
    PERFORM eppm.require_permission('project.edit',ARRAY[selected.project_id]);
    PERFORM eppm.require_permission('project.read',ARRAY[owner]);
    RETURN selected;
END $$;
REVOKE ALL ON FUNCTION eppm.guard_project_dependency() FROM PUBLIC,eppm_runtime;
CREATE TRIGGER authorize_business BEFORE INSERT OR UPDATE OR DELETE ON eppm.project_dependency
    FOR EACH ROW EXECUTE FUNCTION eppm.guard_project_dependency();
CREATE TRIGGER cache_revision AFTER INSERT OR UPDATE OR DELETE ON eppm.project_dependency
    FOR EACH ROW EXECUTE FUNCTION eppm.invalidate_business_caches('project');
REVOKE ALL ON eppm.project_dependency FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON eppm.project_dependency TO eppm_runtime;
GRANT USAGE ON SEQUENCE eppm.project_dependency_id_seq TO eppm_runtime;

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
        UNION
        SELECT entity.id,coalesce(dependency.predecessor_project_id,pred.project_id)
        FROM entities entity JOIN eppm.project_dependency dependency ON dependency.project_id=entity.id
        LEFT JOIN eppm.project_task pred ON pred.id=dependency.predecessor_task_id
        WHERE kind='planning' AND coalesce(dependency.predecessor_project_id,pred.project_id)=ANY(visible)
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

CREATE OR REPLACE FUNCTION eppm.display_cache_revisions() RETURNS jsonb
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
        UNION SELECT dependency.project_id,coalesce(dependency.predecessor_project_id,pred.project_id)
        FROM eppm.project_dependency dependency LEFT JOIN eppm.project_task pred ON pred.id=dependency.predecessor_task_id
        WHERE dependency.project_id=ANY(visible) AND coalesce(dependency.predecessor_project_id,pred.project_id)=ANY(visible)
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

ALTER FUNCTION eppm.display_cache_revisions() SET plan_cache_mode=force_custom_plan;
