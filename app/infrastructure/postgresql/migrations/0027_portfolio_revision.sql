-- A whole-view invalidation key needs source generations, not the dependency
-- graph used by per-project and per-pool calculation keys. Every dependency or
-- assignment mutation already advances its owning project's revision; pool
-- labels/configuration advance the pool revision. Keep those existing triggers
-- and scoped calculation fingerprints unchanged.
CREATE FUNCTION eppm.portfolio_cache_revision() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, eppm, pg_temp
SET plan_cache_mode = force_custom_plan AS $$
DECLARE actor jsonb; visible bigint[]; result jsonb;
BEGIN
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
    SELECT jsonb_build_array(
        encode(eppm_crypto.digest(convert_to(jsonb_build_array(
            jsonb_build_array(identity.epoch,(SELECT oid FROM pg_database WHERE datname=current_database()),
                             actor->'user_id',actor->'session_hash'),
            catalog.revision,security.revision,to_jsonb(visible)
        )::text,'UTF8'),'sha256'),'hex'),
        encode(eppm_crypto.digest(convert_to(jsonb_build_array(
            coalesce((SELECT jsonb_agg(jsonb_build_array(r.project_id,r.generation,r.revision) ORDER BY r.project_id)
                      FROM eppm.project_cache_revision r WHERE r.project_id=ANY(visible)),'[]'::jsonb),
            coalesce((SELECT jsonb_agg(jsonb_build_array(r.pool_id,r.generation,r.revision) ORDER BY r.pool_id)
                      FROM eppm.pool_cache_revision r JOIN eppm.resource_pool pool ON pool.id=r.pool_id),'[]'::jsonb)
        )::text,'UTF8'),'sha256'),'hex')
    ) INTO result FROM eppm.database_identity identity CROSS JOIN eppm.catalog_cache_revision catalog
        CROSS JOIN eppm.app_security_state security WHERE identity.singleton AND catalog.singleton AND security.id=1;
    IF result IS NULL THEN
        RAISE EXCEPTION 'Cache revision unavailable' USING ERRCODE='55000';
    END IF;
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION eppm.portfolio_cache_revision() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION eppm.portfolio_cache_revision() TO eppm_runtime;
