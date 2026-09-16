-- Plan lifecycle and backfill are implemented in the checksummed Python companion.
ALTER TABLE eppm.project_plan ADD COLUMN is_frozen boolean NOT NULL DEFAULT false;
ALTER TABLE eppm.project_plan ADD CONSTRAINT plan_owner_key UNIQUE(id,project_id);
ALTER TABLE eppm.project_plan ALTER COLUMN content DROP NOT NULL;
ALTER TABLE eppm.project_task ADD COLUMN project_plan_id bigint;
ALTER TABLE eppm.project_task ADD COLUMN stable_task_id bigint;
ALTER TABLE eppm.project_task ADD COLUMN is_deleted boolean NOT NULL DEFAULT false;
ALTER TABLE eppm.project_task ADD CONSTRAINT task_plan_owner FOREIGN KEY(project_plan_id,project_id)
    REFERENCES eppm.project_plan(id,project_id) ON DELETE CASCADE;
ALTER TABLE eppm.project_task ADD CONSTRAINT task_plan_key UNIQUE(id,project_plan_id);
CREATE UNIQUE INDEX task_plan_identity ON eppm.project_task(project_plan_id,coalesce(stable_task_id,id));
ALTER TABLE eppm.resource_pool_assignment ADD COLUMN project_plan_id bigint;
ALTER TABLE eppm.resource_pool_assignment ADD COLUMN stable_assignment_id bigint;
ALTER TABLE eppm.resource_pool_assignment ADD CONSTRAINT assignment_plan_owner FOREIGN KEY(project_plan_id,project_id)
    REFERENCES eppm.project_plan(id,project_id) ON DELETE CASCADE;
ALTER TABLE eppm.resource_pool_assignment ADD CONSTRAINT assignment_task_plan FOREIGN KEY(task_id,project_plan_id)
    REFERENCES eppm.project_task(id,project_plan_id) ON DELETE CASCADE;
CREATE UNIQUE INDEX assignment_plan_identity ON eppm.resource_pool_assignment(project_plan_id,coalesce(stable_assignment_id,id));
ALTER TABLE eppm.project_dependency ADD COLUMN project_plan_id bigint REFERENCES eppm.project_plan(id) ON DELETE CASCADE;
ALTER TABLE eppm.project_dependency ADD CONSTRAINT dependency_plan_owner
    FOREIGN KEY(project_plan_id,project_id) REFERENCES eppm.project_plan(id,project_id) ON DELETE CASCADE;
CREATE INDEX task_plan_dates ON eppm.project_task(project_plan_id,start_date,id);
CREATE INDEX task_stable_identity ON eppm.project_task((coalesce(stable_task_id,id)));
CREATE INDEX assignment_plan_pool ON eppm.resource_pool_assignment(project_plan_id,pool_id);
CREATE INDEX project_dependency_plan ON eppm.project_dependency(project_plan_id);
ALTER TABLE eppm.project_task DROP CONSTRAINT project_task_project_id_fkey;
ALTER TABLE eppm.project_task ADD CONSTRAINT project_task_project_id_fkey
    FOREIGN KEY(project_id) REFERENCES eppm.project(id) ON DELETE CASCADE;
ALTER TABLE eppm.project_task DROP CONSTRAINT project_task_predecessor_id_fkey;
ALTER TABLE eppm.project_task ADD CONSTRAINT project_task_predecessor_id_fkey
    FOREIGN KEY(predecessor_id) REFERENCES eppm.project_task(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE eppm.task_dependencies DROP CONSTRAINT task_dependencies_task_id_fkey;
ALTER TABLE eppm.task_dependencies ADD CONSTRAINT task_dependencies_task_id_fkey
    FOREIGN KEY(task_id) REFERENCES eppm.project_task(id) ON DELETE CASCADE;
ALTER TABLE eppm.task_dependencies DROP CONSTRAINT task_dependencies_predecessor_task_id_fkey;
ALTER TABLE eppm.task_dependencies ADD CONSTRAINT task_dependencies_predecessor_task_id_fkey
    FOREIGN KEY(predecessor_task_id) REFERENCES eppm.project_task(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
GRANT SELECT(project_plan_id,stable_task_id,is_deleted),INSERT(project_plan_id,stable_task_id,is_deleted),UPDATE(project_plan_id,stable_task_id,is_deleted)
    ON eppm.project_task TO eppm_runtime;
GRANT UPDATE(is_frozen) ON eppm.project_plan TO eppm_runtime;
GRANT SELECT,UPDATE ON eppm.project_cache_revision TO eppm_runtime;
ALTER TABLE eppm.project_cache_revision ENABLE ROW LEVEL SECURITY;
CREATE POLICY plan_revision_read ON eppm.project_cache_revision FOR SELECT TO eppm_runtime
    USING(project_id=ANY(eppm.permission_projects('project.read')));
CREATE POLICY plan_revision_write ON eppm.project_cache_revision FOR UPDATE TO eppm_runtime
    USING(project_id=ANY(eppm.permission_projects('project.edit')) OR project_id=ANY(eppm.permission_projects('project.approve')));

-- Preserve source-owned protected endpoints when copying a plan. Public Python
-- DTOs redact inaccessible endpoints; this scoped projection supplies exact-copy
-- authorization, without granting access to the predecessor's task details.
CREATE VIEW eppm.plan_row_dependencies WITH(security_barrier=true) AS
    SELECT t.project_plan_id,coalesce(t.stable_task_id,t.id) AS task_id,
        d.predecessor_task_id,d.predecessor_project_id,d.link_type,d.lag_days
    FROM eppm.task_dependencies d JOIN eppm.project_task t ON t.id=d.task_id
    WHERE NOT t.is_deleted AND t.project_id=ANY(eppm.permission_projects('project.read'))
    UNION
    SELECT t.project_plan_id,coalesce(t.stable_task_id,t.id),t.predecessor_id,NULL,'FS',0
    FROM eppm.project_task t WHERE NOT t.is_deleted AND t.predecessor_id IS NOT NULL
        AND t.project_id=ANY(eppm.permission_projects('project.read'))
        AND NOT EXISTS(SELECT 1 FROM eppm.task_dependencies d
            WHERE d.task_id=t.id AND d.predecessor_task_id=t.predecessor_id)
    UNION
    SELECT d.project_plan_id,NULL,d.predecessor_task_id,d.predecessor_project_id,d.link_type,d.lag_days
    FROM eppm.project_dependency d WHERE d.project_id=ANY(eppm.permission_projects('project.read'));
GRANT SELECT ON eppm.plan_row_dependencies TO eppm_runtime;

ALTER POLICY dependency_endpoint_insert ON eppm.task_dependencies WITH CHECK (
    ((predecessor_task_id IS NULL OR predecessor_task_id IN (SELECT id FROM eppm.project_task))
    AND (predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))
    AND ((SELECT project_id FROM eppm.project_task WHERE id=task_id)
            =ANY(eppm.permission_projects('project.approve'))
        OR coalesce(predecessor_project_id,(SELECT project_id FROM eppm.project_task WHERE id=predecessor_task_id))
            =ANY(eppm.permission_projects('project.edit'))))
    OR EXISTS(SELECT 1 FROM eppm.project_task t JOIN eppm.project_plan p ON p.id=t.project_plan_id
        JOIN eppm.plan_row_dependencies d ON d.project_plan_id=p.source_plan_id
            AND d.task_id=coalesce(t.stable_task_id,t.id)
        WHERE t.id=task_dependencies.task_id
            AND d.predecessor_task_id IS NOT DISTINCT FROM task_dependencies.predecessor_task_id
            AND d.predecessor_project_id IS NOT DISTINCT FROM task_dependencies.predecessor_project_id
            AND d.link_type=task_dependencies.link_type AND d.lag_days=task_dependencies.lag_days));
ALTER POLICY project_endpoint_insert ON eppm.project_dependency WITH CHECK (
    ((predecessor_project_id IS NULL OR predecessor_project_id IN (SELECT id FROM eppm.project))
    AND (predecessor_task_id IS NULL OR predecessor_task_id IN
        (SELECT id FROM eppm.project_task t WHERE t.project_id<>project_dependency.project_id)))
    OR EXISTS(SELECT 1 FROM eppm.project_plan p JOIN eppm.plan_row_dependencies d
        ON d.project_plan_id=p.source_plan_id AND d.task_id IS NULL
        WHERE p.id=project_dependency.project_plan_id
            AND d.predecessor_task_id IS NOT DISTINCT FROM project_dependency.predecessor_task_id
            AND d.predecessor_project_id IS NOT DISTINCT FROM project_dependency.predecessor_project_id
            AND d.link_type=project_dependency.link_type AND d.lag_days=project_dependency.lag_days));
