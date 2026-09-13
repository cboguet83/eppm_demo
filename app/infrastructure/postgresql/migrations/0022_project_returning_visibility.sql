-- A project creator with global project.read can read the row being inserted.
-- Enumerating existing IDs at statement start omits that row and incorrectly
-- rejects INSERT ... RETURNING before it becomes visible to later statements.
-- The global branch still checks this exact permission and current actor/MFA.
-- Scoped readers retain their ID filter; write and protected-property guards
-- continue to enforce every mutation independently of SELECT visibility.
DO $$
DECLARE policy_name text;
BEGIN
    FOREACH policy_name IN ARRAY ARRAY['business_select', 'business_update', 'business_delete'] LOOP
        EXECUTE format('ALTER POLICY %I ON eppm.project USING ('
            || '(SELECT eppm.has_global_permission(''project.read''))'
            || ' OR id IN (SELECT unnest(eppm.permission_projects(''project.read''))))', policy_name);
    END LOOP;
END $$;
