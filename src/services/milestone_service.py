"""Historical milestone helpers delegated to the pure scheduling domain."""

from typing import Any

from app.domain.planning.constraints import evaluate_constraints
from app.domain.planning.csv_import import get_csv_template, parse_csv
from app.presentation.components.planning_imports import UploadedCsv, csv_text


class MilestoneService:
    """Keep static entry points during the planning presentation migration."""

    get_csv_template = staticmethod(get_csv_template)
    evaluate_constraints = staticmethod(evaluate_constraints)

    @staticmethod
    def parse_csv(
        uploaded_file: UploadedCsv | None, project_id: int | str
    ) -> list[dict[str, Any]]:
        """Adapt file uploads and project IDs to the pure CSV parser.

        Any describes the historical mixed-value dictionary given to old callers.
        """
        return [{**row, "project_id": project_id} for row in parse_csv(csv_text(uploaded_file))]
