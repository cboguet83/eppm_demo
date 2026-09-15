-- Actual progress survives absence of a task from the current plan.
-- Current-only links disappear with their live endpoint. The authoritative
-- dependency remains in its owner's immutable plan and is shown as unresolved.
ALTER TABLE eppm.task_dependencies DROP CONSTRAINT task_dependencies_predecessor_task_id_fkey;
ALTER TABLE eppm.task_dependencies ADD CONSTRAINT task_dependencies_predecessor_task_id_fkey
    FOREIGN KEY(predecessor_task_id) REFERENCES eppm.project_task(id) ON DELETE CASCADE;
CREATE TABLE eppm.plan_task_actual (
    task_id bigint PRIMARY KEY,
    project_id bigint NOT NULL REFERENCES eppm.project(id) ON DELETE CASCADE,
    progress_pct integer NOT NULL CHECK(progress_pct BETWEEN 0 AND 100)
);
INSERT INTO eppm.plan_task_actual SELECT id,project_id,coalesce(progress_pct,0) FROM eppm.project_task;
ALTER TABLE eppm.plan_task_actual ENABLE ROW LEVEL SECURITY;
CREATE POLICY actual_read ON eppm.plan_task_actual FOR SELECT TO eppm_runtime
    USING(project_id IN (SELECT unnest(eppm.permission_projects('project.read'))));
CREATE POLICY actual_insert ON eppm.plan_task_actual FOR INSERT TO eppm_runtime
    WITH CHECK(project_id IN (SELECT unnest(eppm.permission_projects('project.edit')))
        OR project_id IN (SELECT unnest(eppm.permission_projects('project.approve'))));
CREATE POLICY actual_update ON eppm.plan_task_actual FOR UPDATE TO eppm_runtime
    USING(project_id IN (SELECT unnest(eppm.permission_projects('project.edit')))
        OR project_id IN (SELECT unnest(eppm.permission_projects('project.approve'))))
    WITH CHECK(project_id IN (SELECT unnest(eppm.permission_projects('project.edit')))
        OR project_id IN (SELECT unnest(eppm.permission_projects('project.approve'))));
GRANT SELECT,INSERT,UPDATE ON eppm.plan_task_actual TO eppm_runtime;
ALTER TABLE eppm.plan_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE eppm.plan_status_translation ENABLE ROW LEVEL SECURITY;
CREATE POLICY status_read ON eppm.plan_status FOR SELECT TO eppm_runtime USING((SELECT eppm.has_business_read()));
CREATE POLICY status_label_read ON eppm.plan_status_translation FOR SELECT TO eppm_runtime USING((SELECT eppm.has_business_read()));
CREATE VIEW eppm.plan_task_edit_access WITH (security_barrier=true) AS
    SELECT task.id,
        NOT EXISTS (SELECT 1 FROM eppm.task_dependencies d JOIN eppm.project_task consumer ON consumer.id=d.task_id
            WHERE d.predecessor_task_id=task.id AND NOT consumer.project_id=ANY(eppm.permission_projects('project.edit')))
        AND NOT EXISTS (SELECT 1 FROM eppm.project_task consumer WHERE consumer.predecessor_id=task.id
            AND NOT consumer.project_id=ANY(eppm.permission_projects('project.edit'))) AS removable,
        predecessor_id IS NULL OR predecessor_id IN
            (SELECT id FROM eppm.project_task WHERE project_id=ANY(eppm.permission_projects('project.edit')))
            AS predecessor_editable,
        CASE WHEN predecessor_id IN
            (SELECT id FROM eppm.project_task WHERE project_id=ANY(eppm.permission_projects('project.read')))
            THEN predecessor_id ELSE NULL END AS predecessor_id
    FROM eppm.project_task task WHERE project_id=ANY(eppm.permission_projects('project.read'));
GRANT SELECT ON eppm.plan_task_edit_access TO eppm_runtime;

-- Retain endpoint visibility/ownership restrictions when publishing links.
CREATE POLICY dependency_endpoint_insert ON eppm.task_dependencies AS RESTRICTIVE FOR INSERT TO eppm_runtime
    WITH CHECK (
        (predecessor_task_id IS NULL OR predecessor_task_id IN (SELECT id FROM eppm.project_task))
        AND (predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))
        AND ((SELECT project_id FROM eppm.project_task WHERE id=task_id) IN
                (SELECT unnest(eppm.permission_projects('project.approve')))
            OR coalesce(predecessor_project_id,(SELECT project_id FROM eppm.project_task WHERE id=predecessor_task_id))
                IN (SELECT unnest(eppm.permission_projects('project.edit')))));
CREATE POLICY project_endpoint_insert ON eppm.project_dependency AS RESTRICTIVE FOR INSERT TO eppm_runtime
    WITH CHECK (
        (predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))
        AND (predecessor_task_id IS NULL OR predecessor_task_id IN
            (SELECT id FROM eppm.project_task t WHERE t.project_id<>project_dependency.project_id)));
CREATE POLICY project_endpoint_update ON eppm.project_dependency AS RESTRICTIVE FOR UPDATE TO eppm_runtime
    USING ((predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))
        AND (predecessor_task_id IS NULL OR predecessor_task_id IN (SELECT id FROM eppm.project_task)))
    WITH CHECK ((predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))
        AND (predecessor_task_id IS NULL OR predecessor_task_id IN
            (SELECT id FROM eppm.project_task t WHERE t.project_id<>project_dependency.project_id)));

-- Reuse existing authorization guards for ordinary edits. Approved-plan
-- publication uses scoped approver RLS instead. No lifecycle SQL function.
GRANT EXECUTE ON FUNCTION eppm.runtime_session() TO eppm_runtime;
CREATE TRIGGER authorize_business_insert BEFORE INSERT ON eppm.project_task
    FOR EACH ROW WHEN (CASE WHEN eppm.runtime_session() THEN NOT NEW.project_id=ANY(eppm.permission_projects('project.approve')) ELSE true END)
    EXECUTE FUNCTION eppm.guard_business_write('owned');
CREATE TRIGGER authorize_business_update BEFORE UPDATE ON eppm.project_task
    FOR EACH ROW WHEN (CASE WHEN eppm.runtime_session() THEN
        (NOT NEW.project_id=ANY(eppm.permission_projects('project.approve'))
         OR NOT OLD.project_id=ANY(eppm.permission_projects('project.approve'))) ELSE true END)
    EXECUTE FUNCTION eppm.guard_business_write('owned');
CREATE TRIGGER authorize_business_delete BEFORE DELETE ON eppm.project_task
    FOR EACH ROW WHEN (CASE WHEN eppm.runtime_session() THEN NOT OLD.project_id=ANY(eppm.permission_projects('project.approve')) ELSE true END)
    EXECUTE FUNCTION eppm.guard_business_write('owned');
CREATE TRIGGER authorize_business_insert BEFORE INSERT ON eppm.resource_pool_assignment
    FOR EACH ROW WHEN (CASE WHEN eppm.runtime_session() THEN NOT NEW.project_id=ANY(eppm.permission_projects('project.approve')) ELSE true END)
    EXECUTE FUNCTION eppm.guard_business_write('owned');
CREATE TRIGGER authorize_business_update BEFORE UPDATE ON eppm.resource_pool_assignment
    FOR EACH ROW WHEN (CASE WHEN eppm.runtime_session() THEN NOT NEW.project_id=ANY(eppm.permission_projects('project.approve'))
        OR NOT OLD.project_id=ANY(eppm.permission_projects('project.approve')) ELSE true END)
    EXECUTE FUNCTION eppm.guard_business_write('owned');
CREATE TRIGGER authorize_business_delete BEFORE DELETE ON eppm.resource_pool_assignment
    FOR EACH ROW WHEN (CASE WHEN eppm.runtime_session() THEN NOT OLD.project_id=ANY(eppm.permission_projects('project.approve')) ELSE true END)
    EXECUTE FUNCTION eppm.guard_business_write('owned');
