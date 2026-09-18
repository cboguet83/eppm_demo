"""Project budget editing without rewriting financial transaction history."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal, localcontext

from app.application.ports.project_budget import ProjectBudgetGateway, ProjectBudgetStore
from app.domain.financial_transactions import FinancialRecordType, FinancialTransactionInput, normalize_transaction, validate_identifier
from app.domain.project_budget import ProjectBudgetView, parse_budget_edits


class ProjectBudgetService:
    """Expose the unified yearly table and commit user corrections atomically."""

    def __init__(self, gateway: ProjectBudgetGateway, today: Callable[[], date] = date.today) -> None:
        """Inject authorized persistence and the reporting calendar."""
        self.gateway, self.today = gateway, today

    def years(self) -> range:
        """Show ten fiscal years starting with the preceding year, as in the template."""
        return range(self.today().year - 1, self.today().year + 9)

    def view(self, project_id: int) -> ProjectBudgetView:
        """Read latest budget versions and persisted transaction totals together."""
        validate_identifier(project_id, 'project_id')
        return self.gateway.run(project_id, lambda store: store.view())

    def save(self, project_id: int, revision: str, payload: object) -> bool:
        """Apply valid cells together, rejecting stale views and unauthorized writes."""
        validate_identifier(project_id, 'project_id')

        def operation(store: ProjectBudgetStore) -> bool:
            view = store.view()
            if not isinstance(revision, str) or revision != view.revision:
                raise ValueError('The budget changed since it was loaded. Reload the table before saving.')
            edits = parse_budget_edits(payload, view, self.years())
            current = {(row.wbs, row.kind): row.amounts for row in view.rows}
            changed = False
            with localcontext(prec=60):
                for cell in edits:
                    previous = current[(cell.wbs, cell.kind)].get(cell.year)
                    if cell.kind == 'LIVE_BUDGET':
                        if previous != cell.amount:
                            store.set_live_budget(cell.wbs, cell.year, cell.amount)
                            changed = True
                        continue
                    delta = (cell.amount or Decimal(0)) - (previous or Decimal(0))
                    if not delta:
                        continue
                    value = normalize_transaction(FinancialTransactionInput(
                        project_id=project_id, fiscal_year=cell.year, amount=delta,
                        currency='EUR', exchange_rate=Decimal(1),
                        financial_record_type=FinancialRecordType(cell.kind),
                        spending_type='MANUAL_ADJUSTMENT', wbs=cell.wbs,
                        accounting_date=self.today(), description='Project budget table correction',
                    ))
                    store.create_adjustment(value)
                    changed = True
            return changed

        return self.gateway.run(project_id, operation, write=True)
