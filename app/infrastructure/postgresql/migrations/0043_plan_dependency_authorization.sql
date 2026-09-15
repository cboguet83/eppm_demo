-- Preserve endpoint edit scope for updates/deletes as well as inserts.
-- Scoped approvers may publish the incoming links of their approved projects.
CREATE POLICY dependency_endpoint_update ON eppm.task_dependencies AS RESTRICTIVE FOR UPDATE TO eppm_runtime
    USING (
        (SELECT project_id FROM eppm.project_task WHERE id=task_id)=ANY(eppm.permission_projects('project.approve'))
        OR coalesce(predecessor_project_id,(SELECT project_id FROM eppm.project_task WHERE id=predecessor_task_id))
            =ANY(eppm.permission_projects('project.edit')))
    WITH CHECK (
        (predecessor_task_id IS NULL OR predecessor_task_id IN (SELECT id FROM eppm.project_task))
        AND (predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))
        AND ((SELECT project_id FROM eppm.project_task WHERE id=task_id)=ANY(eppm.permission_projects('project.approve'))
            OR coalesce(predecessor_project_id,(SELECT project_id FROM eppm.project_task WHERE id=predecessor_task_id))
                =ANY(eppm.permission_projects('project.edit'))));
CREATE POLICY dependency_endpoint_delete ON eppm.task_dependencies AS RESTRICTIVE FOR DELETE TO eppm_runtime
    USING (
        (SELECT project_id FROM eppm.project_task WHERE id=task_id)=ANY(eppm.permission_projects('project.approve'))
        OR coalesce(predecessor_project_id,(SELECT project_id FROM eppm.project_task WHERE id=predecessor_task_id))
            =ANY(eppm.permission_projects('project.edit')));
