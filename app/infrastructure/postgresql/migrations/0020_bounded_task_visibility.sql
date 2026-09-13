-- Check each requested endpoint through its primary key and existing task RLS.
-- IN (SELECT id FROM project_task) built complete visible-task hash sets even
-- when a dependency query requested only one project. Scalar correlated reads
-- preserve both-endpoint visibility without scanning unrelated task rows.
DO $$
DECLARE
    target text;
    policy_name text;
    predicate text;
BEGIN
    FOREACH target IN ARRAY ARRAY['task_tag', 'task_dependencies'] LOOP
        predicate := format(
            '(SELECT true FROM eppm.project_task endpoint WHERE endpoint.id=%I.task_id)', target
        );
        IF target = 'task_dependencies' THEN
            predicate := predicate
                || ' AND (predecessor_task_id IS NULL OR (SELECT true FROM eppm.project_task endpoint'
                || ' WHERE endpoint.id=task_dependencies.predecessor_task_id))'
                || ' AND (predecessor_project_id IS NULL OR (SELECT true FROM eppm.project endpoint'
                || ' WHERE endpoint.id=task_dependencies.predecessor_project_id))';
        END IF;
        FOREACH policy_name IN ARRAY ARRAY['business_select', 'business_update', 'business_delete'] LOOP
            EXECUTE format('ALTER POLICY %I ON eppm.%I USING (%s)', policy_name, target, predicate);
        END LOOP;
    END LOOP;
END $$;
