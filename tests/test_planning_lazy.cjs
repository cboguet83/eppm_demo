// Compatibility entry point for extracted loading/state/transport assertions.
// HTTP/source-token guards remain in the actual EPPM adapter tests.
void import('../packages/planning-view/tests/state.test.js');
void import('../packages/planning-view/tests/streamlit.test.js');
require('./test_eppm_planning_adapter.cjs');
