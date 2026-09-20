# Demo WBS budget expansion

The operator helper `expand_demo_budgets` adds 1,500 WBS records without changing
existing allocations or immutable budget revisions. It supports a read-only
preview; writes run in the caller's transaction with table locks. Reusing its
reserved `demo.expansion.` codes is rejected before writes.

Approved totals use these exact bands in both period cohorts:

| Share | Count | Total approved euros |
| --- | ---: | ---: |
| 10% | 150 | 100,000–200,000 |
| 10% | 150 | Above 150,000,000, capped at 200,000,000 |
| 30% | 450 | 200,000–2,000,000 |
| 20% | 300 | 2,000,000–10,000,000 |
| 30% | 450 | 10,000,000–30,000,000 |

500 budgets cover 2020–2025; 1,000 cover 2026–2035. Annual amounts follow
Gaussian weights centered on each period, with standard deviation equal to
one fifth of its duration. Decimal arithmetic and largest-remainder cent
allocation preserve the exact totals. Band totals are evenly spaced, while
project assignment uses a deterministic mixed order of WBS codes.

Only projects without any WBS receive one new WBS at 100%. Completed projects
receive historical WBS; all other statuses receive future WBS. The helper fails
before writing if either cohort lacks sufficient distinct WBS.

A new Approved revision carries forward all previous Approved amounts and adds
the new budgets. A new Proposed revision derives all its values from this
Approved revision, with one reproducible 90–110% multiplier per WBS and inward
cent rounding. WBS without any Approved amounts remain blank.

## Local application, 19 September 2026

- Backup: `data/backups/before-budget-expansion-20260919-134727.dump`.
- Approved snapshot 9; Proposed snapshot 10.
- 988 new project mappings: 100 Completed, 888 other statuses.
- 512 new WBS remain unassigned: 400 historical and 112 future.
- All existing shares and historical financial amounts verified unchanged.
- One pre-existing WBS has no Approved amounts.

## Shifted peak revision, 19 September 2026

The 1,000 future WBS were shifted in a stable mixed order: 100 each by -4, -3,
-2, -1, +1 and +2 years, and 400 by zero years. Overall coverage now spans
2022–2037. Each WBS's earliest peak was copied to its immediately preceding and
following years, increasing totals without renormalizing. The 500 historical
WBS and all project mappings remain unchanged.

- Backup: `data/backups/before-budget-shift-20260919-153021.dump`.
- Approved snapshot 11; Proposed snapshot 12, derived within 90–110% per WBS.
- 888 mapped projects received 1,800 actual and 7,879 commitment transactions.
- Past actuals: 95–105% of approved; no past commitments.
- Current year (2026): actual plus commitment at 80–100% of approved;
  actual share at 20–80% of their combined amount.
- Future years: commitments only, at 0–75% of approved.
- Consistent project/WBS ratios and exact cent arithmetic follow the existing
  spending generator. Repeating spending generation produces no adjustments.
- Existing transactions outside these 888 projects were verified unchanged.

## Five-year plateaus, 19 September 2026

The same 1,000 WBS plateaus were extended two years before their existing start,
making five consecutive peak-value years. Their ending years and other amounts
remain unchanged. Approved snapshot 13 and Proposed snapshot 14 record the change.
The 888 linked projects received 700 actual and 1,275 commitment balancing entries;
the existing spending rules and all project mappings remain unchanged.

Backup: `data/backups/before-plateau-extension-20260919-193928.dump`.

## Six-year plateaus, 19 September 2026

The same 1,000 WBS now have one additional earlier peak-value year. Their ending
years, other WBS amounts, and project mappings are preserved. Approved snapshot 15
and Proposed snapshot 16 record this extension. The 888 linked projects received
800 actual and 488 commitment balancing entries under the existing spending rules.
Repeating the spending calculation requires no further adjustments.

Backup: `data/backups/before-six-year-plateau-20260919-201202.dump`.

## Whole-euro budgets divided by twenty, 19 September 2026

Every yearly amount in the latest Approved (15) and Proposed (16) revisions was
divided by twenty and rounded half up to a whole euro, independently for each
revision. Approved snapshot 17 and Proposed snapshot 18 contain these values;
earlier finance revisions and project/WBS mappings are preserved.

All 1,000 projects with allocated Approved budgets were recalculated across 9,620
project/WBS/year cells. The current demo spending rules supersede the earlier ranges:

- Before 2026: actuals at 95–105% of allocated Approved budget; no commitments.
- 2026: actuals plus commitments at 80–100%; actuals are 30–80% of that total.
- From 2027: commitments at 60–95% of allocated Approved budget; no actuals.

Project ratios remain consistent across WBS codes. Actuals and commitments retain
exact cents. Balancing entries preserve original transaction records and source
links: 2,469 actual and 7,965 commitment entries were appended. Verification found
no further adjustments on an identical rerun. Budget cells rounded to zero also
receive zero spending targets.

Dashboard chart tooltips display whole-number kEUR and FTE; plotted values and
axis precision retain their existing calculations.

Verified backup: `data/backups/before-budget-division-20260919-211420.dump`.
