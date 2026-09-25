"""
Tests for finance_core.google_retry.with_retry (plan 4.4, "Retry scope").
"""

import pytest

from finance_core.google_retry import DELAYS, status_of, with_retry


class FakeResponse:
    def __init__(self, status):
        self.status_code = status
        self.status = status


class FakeHttpError(Exception):
    """Shaped like googleapiclient.errors.HttpError: .resp.status."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.resp = FakeResponse(status)


def flaky(statuses, result="ok"):
    calls = []

    def fn():
        calls.append(1)
        if len(calls) <= len(statuses):
            raise FakeHttpError(statuses[len(calls) - 1])
        return result

    return fn, calls


def test_delays_are_5_15_45():
    assert DELAYS == (5, 15, 45)


@pytest.mark.parametrize("status", [429, 503])
def test_retries_three_times_then_succeeds(status):
    fn, calls = flaky([status] * 3)
    slept = []
    assert with_retry(fn, sleep=slept.append) == "ok"
    assert len(calls) == 4
    assert slept == [5, 15, 45]


def test_gives_up_after_three_retries():
    fn, calls = flaky([503] * 4)
    with pytest.raises(FakeHttpError):
        with_retry(fn, sleep=lambda s: None)
    assert len(calls) == 4


def test_400_is_not_retried():
    fn, calls = flaky([400])
    with pytest.raises(FakeHttpError):
        with_retry(fn, sleep=lambda s: None)
    assert len(calls) == 1


def test_non_http_errors_are_not_retried():
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("bug")

    with pytest.raises(ValueError):
        with_retry(fn, sleep=lambda s: None)
    assert len(calls) == 1


def test_status_of_reads_gspread_api_errors():
    import gspread

    class R:
        status_code = 429
        text = '{"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}'

        def json(self):
            return {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}

    assert status_of(gspread.exceptions.APIError(R())) == 429
