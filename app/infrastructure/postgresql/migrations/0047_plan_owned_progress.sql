-- Progress already resides on each physical task row. Preserve those values,
-- including frozen baselines, and retire the former cross-plan mirror.
DROP TABLE eppm.plan_task_actual;
