-- Python distinguishes explicit baseline capture from ordinary draft creation.
-- Approvers may snapshot their live project schedule; project RLS still applies.
DROP POLICY plan_insert ON eppm.project_plan;
CREATE POLICY plan_insert ON eppm.project_plan FOR INSERT TO eppm_runtime
    WITH CHECK(project_id=ANY(eppm.permission_projects('project.edit'))
        OR project_id=ANY(eppm.permission_projects('project.approve')));
