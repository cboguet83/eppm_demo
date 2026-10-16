-- Preserve active assignment membership and invoker RLS, but avoid hashing all
-- live tasks for a bounded assignment selection. NULL tasks remain valid.
CREATE OR REPLACE VIEW eppm.current_resource_pool_assignment
WITH (security_invoker = true) AS
    SELECT assignment.* FROM eppm.resource_pool_assignment assignment
    WHERE assignment.project_plan_id IN (
        SELECT id FROM eppm.project_plan WHERE is_current
    ) AND (assignment.task_id IS NULL OR EXISTS (
        SELECT 1 FROM eppm.project_task task
        WHERE task.id=assignment.task_id AND NOT task.is_deleted OFFSET 0
    )) WITH LOCAL CHECK OPTION;
