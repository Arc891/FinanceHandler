"""The suite's data guard observes metadata without reading file contents."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from conftest import guard_data_directory


def test_guard_catches_a_write_in_a_stand_in_root(tmp_path):
    data = tmp_path / "data"
    with pytest.raises(pytest.fail.Exception, match=r"data/x"):
        with guard_data_directory(data):
            data.mkdir()
            (data / "x").write_text("synthetic")
    assert (data / "x").exists()  # The guard never cleans up evidence.


def test_guard_accepts_an_unchanged_directory_without_reading(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "existing").write_text("synthetic")

    def no_read(*args, **kwargs):
        raise AssertionError("guard must not read contents")

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", no_read)
        patch.setattr(type(data), "open", no_read)
        with guard_data_directory(data):
            pass


@pytest.mark.parametrize("change", ["size", "mtime", "remove"])
def test_guard_catches_changes_to_existing_entries(tmp_path, change):
    data = tmp_path / "data"
    data.mkdir()
    entry = data / "existing"
    entry.write_text("synthetic")
    with pytest.raises(pytest.fail.Exception, match=r"data/existing"):
        with guard_data_directory(data):
            if change == "size":
                entry.write_text("longer synthetic text")
            elif change == "mtime":
                info = entry.stat()
                os.utime(entry, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
            else:
                entry.unlink()


def test_guard_accepts_an_absent_directory(tmp_path):
    with guard_data_directory(tmp_path / "data"):
        pass


@pytest.mark.parametrize("write_at_import", [False, True], ids=["in-test", "at-import"])
def test_session_guard_fails_a_suite_that_writes_data(tmp_path, write_at_import):
    tests = tmp_path / "tests"
    tests.mkdir()
    source = Path(__file__).with_name("conftest.py")
    (tests / "conftest.py").write_text(source.read_text())
    writer = (
        "data = Path(__file__).parents[1] / 'data'\n"
        "data.mkdir()\n"
        "(data / 'x').write_text('synthetic')\n")
    if write_at_import:
        module = "from pathlib import Path\n" + writer + "def test_writer():\n    pass\n"
    else:
        module = "from pathlib import Path\ndef test_writer():\n" + "".join(
            "    " + line for line in writer.splitlines(keepends=True))
    (tests / "test_writer.py").write_text(module)
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_ADDOPTS": ""})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Tests changed repository data paths:" in result.stdout
    assert str(tmp_path / "data" / "x") in result.stdout
    assert "1 passed" in result.stdout
