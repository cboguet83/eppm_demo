-- Preserve the existing finance input limit when replacing integer cents with
-- native Decimal euros. The existing cent grid and nonnegative checks remain.
ALTER TABLE eppm.finance_amount ADD CONSTRAINT finance_amount_limit
    CHECK (amount <= 92233720368547758.07);
