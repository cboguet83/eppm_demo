"""JSON-lines planning benchmark on an isolated database copy; never edits live data."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projects', type=int, default=100)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='planning-benchmark-') as directory:
        target = str(Path(directory) / 'snapshot.db')
        source = sqlite3.connect('file:' + os.environ.get('DB_NAME', '/app/data/ppm_mock.db') + '?mode=ro', uri=True)
        destination = sqlite3.connect(target)
        source.backup(destination)
        source.close()
        destination.close()
        os.environ['DB_NAME'] = target
        from scripts.benchmark_planning import planning_app
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_function(planning_app, args=(False, True), default_timeout=120)
        if args.projects:
            with sqlite3.connect(target) as conn:
                app.session_state['ms_multi_projects'] = [r[0] for r in conn.execute('SELECT id FROM project ORDER BY id LIMIT ?', (args.projects,))]

        def render():
            app.run()
            if app.exception:
                raise RuntimeError(str(list(app.exception)))
            print(json.dumps({'args': app.session_state['benchmark_payload'], 'server_seconds': app.session_state['benchmark_seconds']}), flush=True)

        render()
        for line in sys.stdin:
            app.session_state['benchmark_event'] = json.loads(line)
            render()


if __name__ == '__main__':
    main()
