"""Measure task pool modal reruns on a disposable PostgreSQL restore."""

import argparse
import json
from time import perf_counter

from streamlit.testing.v1 import AppTest

from scripts.benchmark_planning import run_app
from scripts.benchmark_runtime import BenchmarkContext, add_database_arguments, configured_benchmark


def modal_app(context: 'BenchmarkContext', task_id: int) -> None:
    """Render the real modal without running the surrounding planning page.

    Args:
        context: Restricted pool and identity in the isolated restored database.
        task_id: Task whose pool assignments are displayed.
    """
    import streamlit as st
    from time import perf_counter

    from app.main import create_planning_workspace
    from app.presentation.pages.planning import _manage_task_resource_pools_dialog

    workspace = create_planning_workspace(context.resources, access=context.access)
    task = workspace.planning.get_milestone_by_id(task_id)
    if task is None:
        raise ValueError('The benchmark task is no longer available.')
    st.session_state['benchmark_page_runs'] = st.session_state.get('benchmark_page_runs', 0) + 1
    started = perf_counter()
    _manage_task_resource_pools_dialog(
        task_id, task['task_name'], task['project_id'],
        workspace,
    )
    st.session_state['benchmark_modal_seconds'] = perf_counter() - started


def main() -> None:
    """Benchmark initial opening and widget reruns without editing live data."""
    parser = argparse.ArgumentParser(description=__doc__)
    add_database_arguments(parser)
    parser.add_argument('--task-id', type=int)
    args = parser.parse_args()
    with configured_benchmark(args) as context:
        counts = context.counts()
        app = AppTest.from_function(modal_app, args=(context, context.task_id(args.task_id)), default_timeout=120)
        results = {'tasks': counts[1], 'pools': counts[2]}
        for label in ('open_seconds', 'fte_refresh_seconds', 'period_refresh_seconds'):
            started = perf_counter()
            if label == 'fte_refresh_seconds':
                app.number_input(key='ni_assign_task_fte').set_value(1.5)
            elif label == 'period_refresh_seconds':
                app.radio(key='rb_assign_task_period_mode').set_value('custom')
            run_app(app)
            results[label] = round(app.session_state['benchmark_modal_seconds'], 4)
            results[label.replace('_seconds', '_total_seconds')] = round(perf_counter() - started, 4)
        print(json.dumps(results))


if __name__ == '__main__':
    main()
