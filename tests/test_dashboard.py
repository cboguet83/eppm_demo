"""Pure dashboard rounding, hierarchy, filtering and capacity calculations."""

from decimal import Decimal
import pytest

from app.domain.dashboard import WbsShare, allocated_budget, ancestor, matches, quarterly_shortfall
from app.domain.finance import BudgetSnapshot, BudgetVersion, BudgetRow
from app.domain.resources.models import PoolCapacityDetail, DailyOverassignment


def test_allocated_budget_rounds_per_project_row_and_preserves_gaps_and_zero():
    snapshot=BudgetSnapshot(BudgetVersion(1,1,'Plan','Approved','test',0,None),
        (BudgetRow('A',{2026:Decimal('1.01'),2027:Decimal('0.00')}),BudgetRow('B',{2026:Decimal('100.00')})))
    shares=[WbsShare(1,'A',50),WbsShare(2,'A',50),WbsShare(1,'B',10),WbsShare(1,'MISSING',100)]
    result=allocated_budget(shares+[shares[0]],snapshot,2026)
    assert result.totals=={2026:Decimal('11.02'),2027:Decimal('0')}
    assert result.rows[0][1][2026]==Decimal('0.51') and 2028 not in result.totals
    assert result.unmatched==('MISSING',)
    assert not allocated_budget(shares,None,2026).totals



def test_hierarchy_senior_self_missing_levels_and_cycles():
    functions={i:{'hierarchy_level':i,'manager_function_id':i-1} for i in range(1,7)}
    assert ancestor(5,3,functions)==3 and ancestor(5,4,functions)==4
    assert ancestor(2,4,functions)==2 and ancestor(3,3,functions)==3
    assert ancestor(None,3,functions) is None
    functions[4]['manager_function_id']=2
    assert ancestor(5,3,functions) is None
    functions[4]['manager_function_id']=5
    assert ancestor(5,3,functions) is None



def test_filter_boolean_semantics():
    project={'id':1,'name':'A','fields':{'manager':['1'],'team':['1','2'],'tags':['A','B']}}
    assert matches(project,{'manager':['1','2'],'tags':['A','B']},True)
    assert not matches(project,{'tags':['A','C']},True)
    assert matches(project,{'tags':['A','C']})
    assert not matches(project,{'manager':['2'],'tags':['A']})



def pool(identity, excess, day='2026-01-01', project=1):
    return PoolCapacityDetail(identity,str(identity),1,1,1,True,excess,
        assignments=[{'project_id':project,'fte_assigned':1,'start_date':day,'end_date':day}],
        daily_overassignments=[DailyOverassignment(day,1,1+excess,excess)])



def test_quarterly_peak_sums_only_concurrent_positive_shortfalls():
    result=quarterly_shortfall([pool(1,-50),pool(2,1),pool(3,2),pool(4,2,'2026-02-01'),pool(5,90,project=2)],{1},2026)
    assert result['2026-Q1']==3
    assert result['2026-Q2']==0 and len(result)==80
    assert quarterly_shortfall([pool(1,2,'2026-03-31'),pool(2,3,'2026-04-01')],{1},2026)['2026-Q2']==3



def test_quarter_capacity_uses_concurrent_daily_totals_and_calendar_overrides():
    from dataclasses import replace
    from app.domain.dashboard import quarterly_capacity, responsible_pools, quarter_bounds
    first = replace(pool(1, 2), effective_capacity_fte=2, has_assigned_resources=True,
                    daily_assigned_capacity={'2026-01-01':4})
    second = replace(pool(2, 1, '2026-02-01'), effective_capacity_fte=3, has_assigned_resources=True,
                     daily_assigned_capacity={'2026-02-01':5})
    capacity = quarterly_capacity([first, second, first], 2026)
    assert capacity['2026-Q1'] == 7  # Different-day capacity peaks are not added.
    assert capacity['2026-Q2'] == 5
    start, end = quarter_bounds('2026-Q1', 2026)
    assert responsible_pools([first, second], {1}, start, end) == {1,2}
    with pytest.raises(ValueError):
        quarter_bounds('2026-Q5', 2026)
