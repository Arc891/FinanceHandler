"""
Smoke test for scripts/sandbox_check.py against the fakes, so the live run
fails only on what the real API does differently, never on a script bug.
"""

import sandbox_check

from fakes import FakeWorkbooks


def run(wb, *argv):
    out = []
    code = sandbox_check.main(list(argv) + ["--template", FakeWorkbooks.TEMPLATE_ID], workbooks=wb, stdout_write=out.append)
    return code, "".join(out)


def test_sandbox_check_passes_against_the_fakes_and_deletes_the_month():
    wb = FakeWorkbooks()
    code, out = run(wb)
    assert code == 0, out
    assert "ALL PASSED" in out
    assert wb.created_ids() == []


def test_sandbox_check_reports_a_fidelity_failure_as_plan_a_failing():
    wb = FakeWorkbooks(summary_kw={"income_bound": 34})
    code, out = run(wb)
    assert code == 1
    assert "FAIL" in out and "plan B" in out
    assert wb.created_ids() == []


def test_keep_leaves_the_month():
    wb = FakeWorkbooks()
    code, out = run(wb, "--keep")
    assert code == 0
    assert len(wb.created_ids()) == 1
