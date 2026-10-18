# Extraction performance comparison

Five sequential runs per configuration on the reference Python/Node/Chromium
runtime and 1500 × 1100 viewport are recorded in `candidate.json`. The explicit
collector completed all 25 tests in 112.46 seconds, with no concurrent full suite
or database-copy checks. Synthetic fixture: 100 projects, 1,000 tasks, 127 pools,
730 dated entries per pool and dense dependencies. Native fixture and source-data
isolation checks are unchanged. Every capture passed positive row/cell counts,
<=40 resource rows, <=1 px alignment and filled/equal-width Year geometry checks.

| Configuration | Reference render median | Candidate render median | Reference scroll-work p95 median | Candidate scroll-work p95 median |
| --- | ---: | ---: | ---: | ---: |
| Collapsed | 35.1 ms | 114.7 ms | 4.8 ms | 2.6 ms |
| Expanded | 36.8 ms | 115.6 ms | 4.4 ms | 2.2 ms |
| External links | 38.6 ms | 113.5 ms | 5.0 ms | 2.6 ms |
| Native PostgreSQL | 25.5 ms | 44.3 ms | Not recorded | 1.6 ms |

Synthetic resource medians: 27 live rows, 216 cells and 0 px pane misalignment,
versus reference 26 rows, 208 cells and 0 px. Both retain the same hard bounds.
Native host-edit preparation improved from 0.646 to 0.464 seconds; emitted
payload size is 2,873 bytes versus 2,850. The separate native driver regression
also submits an actual mounted task edit and checks source/restore cleanup.

Render timing brackets synchronous delivery through the actual EPPM bootstrap,
including normalization, checked data ownership and initial drawing, just as
the old diagnostic bracketed its render message. The core stylesheet is loaded
before timing to match the old inline-style setup. Scroll work now brackets the
public animation-frame callback for the complete workspace; the old diagnostic
bracketed its private timeline callback. This broader scroll measurement is
disclosed rather than treated as an identical internal boundary.

Profiling found repeated date parsing and validation/copying of the same graph.
The first migrated diagnostic measured approximately 550 ms. Per-validation date
reuse, one iterative checked JSON copy, frozen owned-message transfer across
adapter/bridge/store, and avoiding an unnecessary initial snapshot serialization
reduce that substantially. Caller-frozen objects still require full validation;
public validation still returns independent copies. Tests cover invalid dates,
mutated input, cycles, aliases, changing accessors and safe own JSON keys.

**Acceptance remains blocked by the initial-render budget.** Every candidate
render median exceeds both the design's 10% and 5 ms limits. The existing budget
has not been changed or waived. The user has been asked whether to retain it or
approve explicit 150 ms synthetic / 60 ms native initial-render limits, keeping
all other gates unchanged. Until a decision or a conforming implementation,
task 5.5 and final acceptance remain incomplete; these measurements do not
authorize archive or PR delivery.

An earlier diagnostic collector was interrupted after 17 successful tests when
the full suite began. Its measurements are excluded here: overlapping copy
cleanup assertions caused one diagnostic cleanup failure, and a busy host is
unsuitable for timing comparison. The final sequential collector supersedes it.
