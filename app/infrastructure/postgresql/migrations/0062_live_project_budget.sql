-- One mutable live budget per project, WBS and fiscal year; no revisions.
ALTER TABLE eppm.project_financial_transaction DROP CONSTRAINT project_financial_transaction_financial_record_type_check;
ALTER TABLE eppm.project_financial_transaction ADD CONSTRAINT project_financial_transaction_financial_record_type_check CHECK (financial_record_type IN ('COMMITMENT','ACTUAL','LIVE_BUDGET'));
ALTER TABLE eppm.project_financial_transaction ADD CONSTRAINT live_budget_nonnegative CHECK (financial_record_type <> 'LIVE_BUDGET' OR amount >= 0);
CREATE UNIQUE INDEX project_live_budget_cell ON eppm.project_financial_transaction(project_id,wbs,fiscal_year) WHERE financial_record_type='LIVE_BUDGET';
DROP POLICY transaction_insert ON eppm.project_financial_transaction;
DROP POLICY transaction_update ON eppm.project_financial_transaction;
DROP POLICY transaction_delete ON eppm.project_financial_transaction;
CREATE POLICY transaction_insert ON eppm.project_financial_transaction FOR INSERT TO eppm_runtime
    WITH CHECK (project_id IN (SELECT unnest(eppm.permission_projects('project.read')))
        AND ((SELECT eppm.has_global_permission('finance.edit'))
             OR (financial_record_type IN ('COMMITMENT','ACTUAL','LIVE_BUDGET')
                 AND project_id IN (SELECT unnest(eppm.permission_projects('project.edit'))))));
CREATE POLICY transaction_update ON eppm.project_financial_transaction FOR UPDATE TO eppm_runtime
    USING (project_id IN (SELECT unnest(eppm.permission_projects('project.read')))
        AND ((SELECT eppm.has_global_permission('finance.edit'))
             OR (financial_record_type IN ('COMMITMENT','ACTUAL','LIVE_BUDGET')
                 AND project_id IN (SELECT unnest(eppm.permission_projects('project.edit'))))))
    WITH CHECK (project_id IN (SELECT unnest(eppm.permission_projects('project.read')))
        AND ((SELECT eppm.has_global_permission('finance.edit'))
             OR (financial_record_type IN ('COMMITMENT','ACTUAL','LIVE_BUDGET')
                 AND project_id IN (SELECT unnest(eppm.permission_projects('project.edit'))))));
CREATE POLICY transaction_delete ON eppm.project_financial_transaction FOR DELETE TO eppm_runtime
    USING (project_id IN (SELECT unnest(eppm.permission_projects('project.read')))
        AND ((SELECT eppm.has_global_permission('finance.edit'))
             OR (financial_record_type IN ('COMMITMENT','ACTUAL','LIVE_BUDGET')
                 AND project_id IN (SELECT unnest(eppm.permission_projects('project.edit'))))));
