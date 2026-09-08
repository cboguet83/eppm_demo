"""Measure task pool modal reruns on a temporary copy of the development DB."""

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from time import perf_counter

from streamlit.testing.v1 import AppTest


def modal_app(db_path: str, task_id: int) -> None:
    """Render the real modal without running the surrounding planning page.

    Args:
        db_path: Path to the isolated benchmark database.
        task_id: Task whose pool assignments are displayed.
    """
    import streamlit as st
    from time import perf_counter

    from app.main import create_planning_workspace
    from app.presentation.pages.planning import _manage_task_resource_pools_dialog

    workspace = create_planning_workspace(db_path)
    task = workspace.planning.get_milestone_by_id(task_id)
    st.session_state['benchmark_page_runs'] = st.session_state.get('benchmark_page_runs', 0) + 1
    started = perf_counter()
    _manage_task_resource_pools_dialog(
        task_id, task['task_name'], task['project_id'],
        workspace,
    )
    st.session_state['benchmark_modal_seconds'] = perf_counter() - started


def main() -> None:
    """Benchmark initial opening and widget reruns without editing live data."""
    from app.shared.config import config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', type=int)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        db_path = str(Path(directory) / 'benchmark.db')
        with sqlite3.connect(f'file:{Path(config.db_path).as_posix()}?mode=ro', uri=True) as source:
            with sqlite3.connect(db_path) as destination:
                source.backup(destination)
                counts = destination.execute(
                    'SELECT (SELECT COUNT(*) FROM project_task), (SELECT COUNT(*) FROM resource_pool)'
                ).fetchone()
                row = destination.execute(
                    'SELECT task_id FROM resource_pool_assignment WHERE task_id IS NOT NULL '
                    'UNION ALL SELECT id FROM project_task LIMIT 1'
                ).fetchone()
        if row is None:
            raise RuntimeError('No tasks available for the modal benchmark.')
        app = AppTest.from_function(modal_app, args=(db_path, args.task_id or row[0]), default_timeout=120)
        results = {'tasks': counts[0], 'pools': counts[1]}
        for label in ('open_seconds', 'fte_refresh_seconds', 'period_refresh_seconds'):
            started = perf_counter()
            if label == 'fte_refresh_seconds':
                app.number_input(key='ni_assign_task_fte').set_value(1.5)
            elif label == 'period_refresh_seconds':
                app.radio(key='rb_assign_task_period_mode').set_value('custom')
            app.run()
            if app.exception:
                raise RuntimeError(str(list(app.exception)))
            results[label] = round(app.session_state['benchmark_modal_seconds'], 4)
            results[label.replace('_seconds', '_total_seconds')] = round(perf_counter() - started, 4)
        print(json.dumps(results))


if __name__ == '__main__':
    main()
