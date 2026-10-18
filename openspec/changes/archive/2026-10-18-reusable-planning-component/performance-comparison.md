# Extraction performance comparison

Five sequential runs per configuration on the reference Python/Node/Chromium
runtime and 1500 × 1100 viewport are recorded in `candidate.json`. The explicit
collector completed all 25 tests in 107.13 seconds after task 7.3 on integrated main, with no concurrent full suite
or database-copy checks. Synthetic fixture: 100 projects, 1,000 tasks, 127 pools,
730 dated entries per pool and dense dependencies. Native fixture and source-data
isolation checks are unchanged. Every capture passed positive row/cell counts,
<=40 resource rows, <=1 px alignment and filled/equal-width Year geometry checks.

| Configuration | Reference render median | Candidate render median | Reference scroll-work p95 median | Candidate scroll-work p95 median |
| --- | ---: | ---: | ---: | ---: |
| Collapsed | 35.1 ms | 121.1 ms | 4.8 ms | 1.5 ms |
| Expanded | 36.8 ms | 118.8 ms | 4.4 ms | 1.7 ms |
| External links | 38.6 ms | 124.0 ms | 5.0 ms | 1.6 ms |
| Native PostgreSQL | 25.5 ms | 39.8 ms | Not recorded | 0.7 ms |

Synthetic resource medians: 27 live rows, 216 cells and 0 px pane misalignment,
versus reference 26 rows, 208 cells and 0 px. Both retain the same hard bounds.
Native host-edit preparation improved from 0.646 to 0.522 seconds; emitted
payload size is 2,873 bytes versus 2,850. The separate native driver regression
also submits an actual mounted task edit and checks source/restore cleanup.
The native candidate `tasks: 0` counts the initial lazy payload; `visibleTasks: 2`
confirms hydrated task rows before scrolling. The reference `tasks: 2` counted
hydrated private state. This count-field boundary differs; fixture contents and
the timed initial render-message boundary remain unchanged.

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

**The final captures pass the explicitly approved budget.** On 2026-10-18 the
user accepted revised initial-render median limits of **150 ms synthetic /
60 ms native**, retaining every other gate. The three synthetic medians above
are below 150 ms and native rendering is below 60 ms. Other applicable timings
retain the original rule: a regression must exceed both 10% and 5 ms to block
acceptance. Scroll-work medians improve, frame p95 remains within that rule,
and all row/alignment/loading/geometry bounds pass. This decision changes only
initial-render limits; contract validation and input ownership remain intact.
Task 5.5 is satisfied; full strict-suite acceptance is still required before
archive or PR delivery.

An earlier diagnostic collector was interrupted after 17 successful tests when
the full suite began. Its measurements are excluded here: overlapping copy
cleanup assertions caused one diagnostic cleanup failure, and a busy host is
unsuitable for timing comparison. The final sequential collector supersedes it.

## Current-main scroll correction

The first integrated collection passed initial-render and hard assertions but
failed collapsed maximum scroll work: 12.5 ms versus reference 6.9 ms, exceeding
both unchanged limits. Every capture is retained in `scroll-regression.json`.
A DOM profile located the slow frame in resource redraw (360 new elements).
Task 7.3 avoids unchanged resource-control/layout and toolbar text writes on
scroll frames, with mounted static-node identity and real label-update tests.
The menu visual comparison waits for actual CSS transitions to finish; its
configured-style assertions remain intact.

Final maximum-scroll-work medians are 8.9 / 8.6 / 9.4 ms versus reference
6.9 / 7.4 / 8.2 ms for collapsed / expanded / external configurations. None
exceeds the reference by 5 ms. Native maximum/p95 work is 0.7 ms (no original
work metric); native frame p95 improves from 33.3 to 16.9 ms. Every applicable
render, maximum/p95 scroll-work and frame metric was compared; no gate was
waived. The final capture includes the prepared-asset manifest hash.
