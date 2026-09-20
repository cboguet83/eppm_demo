"""Batched, policy-scoped financial aggregates for project reporting readers."""

FINANCIAL_CTES = '''project_spending AS MATERIALIZED (
    SELECT project_id,
        coalesce(sum(amount_base_currency) FILTER (WHERE financial_record_type='COMMITMENT'),0) planned_budget,
        coalesce(sum(amount_base_currency) FILTER (WHERE financial_record_type='ACTUAL'),0) actual_budget
    FROM eppm.project_financial_transaction
    WHERE financial_record_type IN ('COMMITMENT','ACTUAL') GROUP BY project_id
), project_approved AS MATERIALIZED (
    SELECT pw.project_id,sum(a.amount * pw.percentage / 100) approved_budget
    FROM eppm.project_wbs pw JOIN eppm.wbs w ON w.id=pw.wbs_id
    JOIN eppm.finance_amount a ON a.code=w.code AND a.snapshot_id=(
        SELECT s.id FROM eppm.finance_snapshot s WHERE s.status='Approved' AND s.sealed
            AND NOT EXISTS(SELECT 1 FROM eppm.finance_cancellation c WHERE c.snapshot_id=s.id)
        ORDER BY s.number DESC LIMIT 1)
    GROUP BY pw.project_id
)'''

FINANCIAL_JOINS = '''LEFT JOIN project_spending spending ON spending.project_id=p.id
    LEFT JOIN project_approved approved ON approved.project_id=p.id'''
