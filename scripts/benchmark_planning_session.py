"""JSON-lines planning benchmark on an isolated database copy; never edits live data."""

import argparse
import json
import sys

from scripts.benchmark_planning import create_app, run_app
from scripts.benchmark_runtime import add_database_arguments, configured_benchmark


def main() -> None:
    """Emit chart payloads for component events using one disposable native pool."""
    parser = argparse.ArgumentParser(description=__doc__)
    add_database_arguments(parser)
    parser.add_argument('--projects', type=int, default=100)
    args = parser.parse_args()
    with configured_benchmark(args) as context:
        app = create_app(context, projects=args.projects, profile=False, capture=True)

        def render() -> None:
            run_app(app)
            print(json.dumps({'args': app.session_state['benchmark_payload'], 'server_seconds': app.session_state['benchmark_seconds']}), flush=True)

        render()
        for line in sys.stdin:
            app.session_state['benchmark_event'] = json.loads(line)
            render()


if __name__ == '__main__':
    main()
