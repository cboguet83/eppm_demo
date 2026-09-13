"""Bounded error examples must not truncate aggregate database failure counts."""

import pytest

from tests.performance import observer


def test_database_error_counter_survives_example_limit_and_preserves_the_exception(monkeypatch):
    monkeypatch.setattr(observer, "_totals", {})
    monkeypatch.setattr(observer, "_failures", [])
    error = ValueError("private driver message must not be retained")

    def fail():
        raise error

    observed = observer.timed("db_client_execute", fail)
    for _ in range(25):
        with pytest.raises(ValueError) as raised:
            observed()
        assert raised.value is error
    assert len(observer._failures) == 20
    assert observer._totals["db_failures_ValueError"]["count"] == 25
    assert observer._totals["db_client_execute"]["count"] == 25
    assert all(set(example) == {"metric", "category", "locations"} for example in observer._failures)
    assert "private driver" not in repr(observer._failures)


def test_successful_observed_operation_preserves_inputs_and_result_without_an_error_count(monkeypatch):
    monkeypatch.setattr(observer, "_totals", {})
    result = object()

    def execute(value, *, option):
        assert value == 17 and option is True
        return result

    assert observer.timed("db_client_execute", execute)(17, option=True) is result
    assert set(observer._totals) == {"db_client_execute"}
