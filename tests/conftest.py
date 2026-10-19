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


@contextmanager
def guard_data_directory(directory):
    """Fail on added, changed or removed paths, using stat information only."""
    before = _data_snapshot(directory)
    try:
        yield
    finally:
        after = _data_snapshot(directory)
        changed = sorted(name for name in before.keys() | after.keys()
                         if before.get(name) != after.get(name))
        if changed:
            paths = [str(directory / name) for name in changed]
            pytest.fail("Tests changed repository data paths:\n" + "\n".join(paths))


@pytest.fixture(scope="session", autouse=True)
def no_repository_data_writes():
    with guard_data_directory(Path(__file__).resolve().parents[1] / "data"):
        yield
