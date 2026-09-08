"""Measure planning preparation (not browser paint) without seeding the database.

Run: docker compose exec -T app python -m scripts.benchmark_planning
"""

from streamlit.testing.v1 import AppTest


def planning_app(profile=True, capture=False):
    import cProfile
    import io
    import pstats
    import time
    from contextlib import nullcontext
    from unittest.mock import patch

    import streamlit as st
    from src.repositories.project_repo import ProjectRepository
    from src.repositories.milestone_repo import MilestoneRepository
    from src.repositories.tag_repo import TagRepository
    from src.repositories.resource_pool_repo import ResourcePoolRepository
    from src.repositories.organization_repo import OrganizationRepository
    from src.repositories.schema_repo import SchemaRepository
    from src.views.planning_view import render_planning_milestones
    from src.database.connection import get_db

    with get_db() as conn:
        st.session_state["benchmark_counts"] = conn.execute(
            "SELECT (SELECT COUNT(*) FROM project), (SELECT COUNT(*) FROM project_task), "
            "(SELECT COUNT(*) FROM resource_pool)"
        ).fetchone()

    profiler = cProfile.Profile()
    started = time.perf_counter()
    if profile:
        profiler.enable()
    with (patch('src.views.planning_view._interactive_gantt', return_value=None) if capture else nullcontext()) as component:
        event = st.session_state.pop('benchmark_event', None)
        if event:
            from src.views.planning_view import _handle_gantt_component_change
            st.session_state['planning_lazy_gantt'] = event
            _handle_gantt_component_change('planning_lazy_gantt', MilestoneRepository())
        render_planning_milestones(
            ProjectRepository(), MilestoneRepository(), TagRepository(),
            ResourcePoolRepository(), OrganizationRepository(), SchemaRepository(),
        )
        if capture:
            st.session_state['benchmark_payload'] = {
                k: v for k, v in component.call_args.kwargs.items() if k not in ('on_change', 'key')}
    if profile:
        profiler.disable()
    st.session_state["benchmark_seconds"] = time.perf_counter() - started
    output = io.StringIO()
    if profile:
        pstats.Stats(profiler, stream=output).sort_stats("cumtime").print_stats(25)
    st.session_state["benchmark_profile"] = output.getvalue()


if __name__ == "__main__":
    import argparse
    import json
    from src.database.connection import get_db
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projects', type=int, default=100, help='Selected project count; 0 selects all')
    parser.add_argument('--no-profile', action='store_true')
    parser.add_argument('--dump-payload', action='store_true', help='Print chart JSON for the local browser benchmark')
    args = parser.parse_args()
    app = AppTest.from_function(planning_app, args=(not args.no_profile, args.dump_payload), default_timeout=120)
    if args.projects > 0:
        with get_db() as conn:
            app.session_state['ms_multi_projects'] = [r[0] for r in conn.execute('SELECT id FROM project ORDER BY id LIMIT ?', (args.projects,))]
    for label in ("First load", "Warm rerun"):
        app.run()
        if app.exception:
            raise RuntimeError(str(list(app.exception)))
        if args.dump_payload:
            print(json.dumps(app.session_state['benchmark_payload']))
            break
        print(f"{label}: {app.session_state['benchmark_seconds']:.3f}s ({'without' if args.no_profile else 'with'} profiler)")
        print("Projects, tasks, pools:", app.session_state["benchmark_counts"])
        print(app.session_state["benchmark_profile"])
