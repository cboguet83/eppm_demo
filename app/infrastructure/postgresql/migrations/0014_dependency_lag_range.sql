-- Preserve the signed 64-bit lag range accepted by existing schedule templates.
-- Applied baselines remain immutable; native date comparisons do not add lags
-- to PostgreSQL dates and therefore also handle either extreme without overflow.
ALTER TABLE eppm.task_dependencies ALTER COLUMN lag_days TYPE bigint;
