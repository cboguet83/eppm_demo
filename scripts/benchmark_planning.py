"""Measure planning preparation (not browser paint) without seeding the database.

Run: docker compose exec -T app python -m scripts.benchmark_planning
"""

from streamlit.testing.v1 import AppTest


def planning_app():
    import cProfile
    import io
    import pstats
    import time

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
    profiler.enable()
    render_planning_milestones(
        ProjectRepository(), MilestoneRepository(), TagRepository(),
        ResourcePoolRepository(), OrganizationRepository(), SchemaRepository(),
    )
    profiler.disable()
    st.session_state["benchmark_seconds"] = time.perf_counter() - started
    output = io.StringIO()
    pstats.Stats(profiler, stream=output).sort_stats("cumtime").print_stats(25)
    st.session_state["benchmark_profile"] = output.getvalue()


if __name__ == "__main__":
    app = AppTest.from_function(planning_app, default_timeout=120)
    for label in ("First load", "Warm rerun"):
        app.run()
        if app.exception:
            raise RuntimeError(str(list(app.exception)))
        print(f"{label}: {app.session_state['benchmark_seconds']:.3f}s (with profiler)")
        print("Projects, tasks, pools:", app.session_state["benchmark_counts"])
        print(app.session_state["benchmark_profile"])
