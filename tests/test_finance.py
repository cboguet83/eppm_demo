"""Database-independent Finance parsing, exact euros and CSV validation."""

import csv
from decimal import Decimal
import io

import pytest

from app.domain.finance import (
    BudgetRow, FinanceError, export_csv, normalize_rows, parse_amount, parse_csv,
    preserve_history,
)


def rows(code='A', amount='100.01', year=2026):
    return [{'code': code, 'amounts': {str(year): amount}}]



@pytest.mark.parametrize('value,expected', [('', None), (' ', None), ('0', Decimal('0')), ('0.10', Decimal('0.10')),
    ('100,01', Decimal('100.01')), ('92233720368547758.07', Decimal('92233720368547758.07'))])
def test_finance_uses_exact_decimal_euros_and_distinguishes_blank_from_zero(value, expected):
    assert parse_amount(value, 2, 2026) == expected



@pytest.mark.parametrize('value', ['-1', 'NaN', 'inf', '1e3', '1.001', '1,000.00', '=1+1', '92233720368547758.08', True, 1.1, None])
def test_invalid_amount_explains_row_and_year(value):
    with pytest.raises(FinanceError, match='Row 2, year 2026'):
        parse_amount(value, 2, 2026)



@pytest.mark.parametrize('raw,key', [([{'code':'A B','amounts':{}}], 'code'), (rows()*2, 'duplicate'),
    (rows(year=2025), 'years'), (rows(year=2041), 'years'), ([{}], 'rows'), (None,'rows'),
    ([{'code':None,'amounts':{}}], 'code')])
def test_grid_rejects_invalid_codes_duplicate_rows_and_historical_edits(raw, key):
    with pytest.raises(FinanceError) as caught:
        normalize_rows(raw, 2026)
    assert caught.value.code == key



def test_csv_round_trip_and_precise_import_errors():
    source = (BudgetRow('-ABC',{2025:Decimal('0.12'),2026:Decimal('0.10'),2040:Decimal('9.99')}), BudgetRow('#FICTIVE',{}))
    text = export_csv(source, {'-ABC':'=DO_NOT_EXECUTE()'}, 2026)
    assert "'-ABC;'=DO_NOT_EXECUTE()" in text
    assert parse_csv('\ufeff'+text,2026) == (BudgetRow('-ABC',{2026:Decimal('0.10'),2040:Decimal('9.99')}),BudgetRow('#FICTIVE',{}))
    csv_rows = list(csv.reader(io.StringIO(text),delimiter=';'))
    csv_rows[1][2] = '12,34'
    out = io.StringIO(); csv.writer(out).writerows(csv_rows)
    assert parse_csv(out.getvalue(),2026)[0].amounts[2026] == Decimal('12.34')
    for content, key in [('wrong\n','headers'), (text+'too;short\n','columns'), (text.replace('0.10','-1'),'amount'),
                         (text+text.splitlines()[1]+'\n','duplicate'), ('\x00','csv'), ('x'*2097153,'csv')]:
        with pytest.raises(FinanceError) as caught:
            parse_csv(content,2026)
        assert caught.value.code == key



def test_limits_account_for_history_multibyte_files_and_malformed_csv():
    with pytest.raises(FinanceError,match='10,000'):
        preserve_history(tuple(BudgetRow(str(i),{2025:Decimal('0.01')}) for i in range(10000)),(BudgetRow('new',{}),),2026)
    header=export_csv((),{},2026)
    for text in ['é'*1100000,'\ud800',header+'"unclosed',header+('A;'+';'*15+'\n')*10001]:
        with pytest.raises(FinanceError): parse_csv(text,2026)



def test_blank_grid_rows_are_ignored_and_amount_without_code_identifies_row():
    assert normalize_rows([{'code':' ','amounts':{'2026':''}},*rows(),{'code':'','amounts':{}}],2026)==(BudgetRow('A',{2026:Decimal('100.01')}),)
    with pytest.raises(FinanceError,match='Row 2'):
        normalize_rows([{'code':'','amounts':{}},{'code':'','amounts':{'2026':'0'}}],2026)
