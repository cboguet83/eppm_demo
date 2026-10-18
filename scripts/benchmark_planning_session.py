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

        def render(acknowledgement: str | None = None) -> None:
            """Emit a render with the receipt normally added by the widget adapter.

            Args:
                acknowledgement: Nonce of the event handled in this rerun.
            """
            run_app(app)
            payload = dict(app.session_state['benchmark_payload'])
            if acknowledgement is not None:
                payload['ack_nonce'] = acknowledgement
            print(json.dumps({'args': payload, 'server_seconds': app.session_state['benchmark_seconds']}), flush=True)

        render()
        for line in sys.stdin:
            event = json.loads(line)
            app.session_state['benchmark_event'] = event
            render(event.get('nonce'))


if __name__ == '__main__':
    main()
