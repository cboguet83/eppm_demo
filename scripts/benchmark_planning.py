"""Measure planning preparation on a disposable PostgreSQL restore, excluding browser paint."""

from streamlit.testing.v1 import AppTest

from scripts.benchmark_runtime import BenchmarkContext, add_database_arguments, configured_benchmark


def planning_app(context: 'BenchmarkContext', profile: bool = True, capture: bool = False) -> None:
    """Render native planning with restricted resources owned by the caller."""
    import cProfile
    import io
    import pstats
    import time
    from contextlib import nullcontext
    from unittest.mock import patch

    import streamlit as st
    from app.main import create_planning_workspace
    from app.presentation.pages.planning import render_planning_milestones
    workspace = create_planning_workspace(context.resources, access=context.access)
    st.session_state['benchmark_counts'] = context.counts()

    profiler = cProfile.Profile()
    started = time.perf_counter()
    if profile:
        profiler.enable()
    with (patch('app.presentation.pages.planning._interactive_gantt', return_value=None) if capture else nullcontext()) as component:
        event = st.session_state.pop('benchmark_event', None)
        if event:
            from app.presentation.pages.planning import _handle_gantt_component_change
            st.session_state['planning_lazy_gantt'] = event
            _handle_gantt_component_change('planning_lazy_gantt', workspace)
        render_planning_milestones(workspace)
        if capture and component.call_args is not None:
            st.session_state['benchmark_payload'] = {
                k: v for k, v in component.call_args.kwargs.items() if k not in ('on_change', 'key')}
            # The standalone diagnostic has no ASGI application. Exercise its
            # existing callback path; HTTP/browser acceptance uses the real app.
            st.session_state['benchmark_payload']['task_endpoint'] = None
    if profile:
        profiler.disable()
    st.session_state["benchmark_seconds"] = time.perf_counter() - started
    output = io.StringIO()
    if profile:
        pstats.Stats(profiler, stream=output).sort_stats("cumtime").print_stats(25)
    st.session_state["benchmark_profile"] = output.getvalue()


def create_app(context: BenchmarkContext, *, projects: int = 100,
               profile: bool = True, capture: bool = False) -> AppTest:
    """Select projects before the first timed render of the real planning page."""
    app = AppTest.from_function(planning_app, args=(context, profile, capture), default_timeout=120)
    app.session_state['ms_multi_projects'] = context.project_ids(projects)
    return app


def run_app(app: AppTest) -> None:
    """Reject failed renders without printing potentially sensitive exceptions."""
    app.run()
    if app.exception or app.error:
        raise RuntimeError('Planning benchmark could not render successfully.')


def main() -> None:
    """Profile first and warm renders using explicit operator configuration."""
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    add_database_arguments(parser)
    parser.add_argument('--projects', type=int, default=100, help='Selected project count; 0 selects all')
    parser.add_argument('--no-profile', action='store_true')
    parser.add_argument('--dump-payload', action='store_true', help='Print chart JSON for the local browser benchmark')
    args = parser.parse_args()
    with configured_benchmark(args) as context:
        app = create_app(context, projects=args.projects, profile=not args.no_profile, capture=args.dump_payload)
        for label in ('First load', 'Warm rerun'):
            run_app(app)
            if args.dump_payload:
                print(json.dumps(app.session_state['benchmark_payload']))
                break
            print(f"{label}: {app.session_state['benchmark_seconds']:.3f}s ({'without' if args.no_profile else 'with'} profiler)")
            print('Projects, tasks, pools:', app.session_state['benchmark_counts'])
            print(app.session_state['benchmark_profile'])


if __name__ == '__main__':
    main()
