-- Restore the explicit trusted-before-temporary resolution used by other helpers.
-- Keep the existing trigger body and all applied migration bytes unchanged.
ALTER FUNCTION eppm.guard_wbs_total()
    SET search_path = pg_catalog, eppm, pg_temp;
ALTER FUNCTION eppm.guard_team_parent_cycle()
    SET search_path = pg_catalog, eppm, pg_temp;
ALTER FUNCTION eppm.guard_pool_type_parent_cycle()
    SET search_path = pg_catalog, eppm, pg_temp;
