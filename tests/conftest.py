"""Observe repository data metadata; never redirect production defaults globally."""

from contextlib import contextmanager
from pathlib import Path
import stat

import pytest


def _data_snapshot(directory):
    entries = {}

    def visit(path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        entries[path.relative_to(directory).as_posix()] = (
            info.st_size, info.st_mtime_ns)
        # Do not follow links into other state directories.
        if stat.S_ISDIR(info.st_mode):
            for child in path.iterdir():
                visit(child)

    visit(directory)
    return entries


def changed_data_paths(directory, before):
    """Paths added, changed or removed since ``before``, by stat information only."""
    after = _data_snapshot(directory)
    return [str(directory / name) for name in sorted(before.keys() | after.keys())
            if before.get(name) != after.get(name)]


@contextmanager
def guard_data_directory(directory):
    """Fail on added, changed or removed paths, using stat information only."""
    before = _data_snapshot(directory)
    try:
        yield
    finally:
        changed = changed_data_paths(directory, before)
        if changed:
            pytest.fail("Tests changed repository data paths:\n" + "\n".join(changed))


DATA = Path(__file__).resolve().parents[1] / "data"


def pytest_sessionstart(session):
    # Before collection, so a test module that writes at import time is caught too.
    session.config._data_before = _data_snapshot(DATA)


def pytest_sessionfinish(session, exitstatus):
    changed = changed_data_paths(DATA, session.config._data_before)
    if changed:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        reporter.write_line("Tests changed repository data paths:", red=True)
        for path in changed:
            reporter.write_line(path, red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
