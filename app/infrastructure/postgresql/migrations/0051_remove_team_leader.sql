-- Remove the obsolete team leader without transferring it to another role.
-- Update the existing private staffing reader before dropping its source column.
DO $$
DECLARE definition text;
BEGIN
    SELECT pg_get_functiondef('eppm.capacity_contributions(bigint[])'::regprocedure)
        INTO definition;
    definition := replace(definition, '            UNION SELECT t.manager_function_id
            UNION SELECT t.leader_function_id
            UNION SELECT f.function_id FROM eppm.function f
                WHERE f.manager_function_id=t.manager_function_id AND
                    (SELECT count(*) FROM eppm.team_function tf WHERE tf.team_id=m.target_id)
                    + (t.manager_function_id IS NOT NULL)::integer + (t.leader_function_id IS NOT NULL)::integer <= 2', '');
    IF strpos(definition, 't.leader_function_id') > 0 OR strpos(definition, 't.manager_function_id') > 0 THEN
        RAISE EXCEPTION 'Unexpected team staffing definition; explicit membership migration aborted';
    END IF;
    EXECUTE definition;
END $$;

ALTER TABLE eppm.team DROP COLUMN leader_function_id;

-- Staffing has changed even though no team row was updated.
UPDATE eppm.catalog_cache_revision SET revision = revision + 1;
