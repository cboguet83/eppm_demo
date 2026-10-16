-- Preserve native RLS while resolving copied-plan endpoints by plain columns.
CREATE INDEX project_task_stable_reference ON eppm.project_task(stable_task_id)
    WHERE stable_task_id IS NOT NULL;
