"""Defaulted settings and paths use synthetic config and never touch runtime data."""

from pathlib import Path
import sys
from types import ModuleType

import pytest

import config
from finance_core import config_access


@pytest.fixture
def fake_config(monkeypatch):
    module = ModuleType("config.config_settings")
    monkeypatch.setitem(sys.modules, "config.config_settings", module)
    monkeypatch.setattr(config, "config_settings", module, raising=False)
    return module


@pytest.mark.parametrize("value", ["configured", 0, False, None])
def test_setting_returns_present_value_even_if_falsey(fake_config, value):
    fake_config.TEST_SETTING = value
    assert config_access.setting("TEST_SETTING", "fallback") == value


def test_missing_setting_returns_explicit_default(fake_config):
    default = object()
    assert config_access.setting("MISSING_SETTING", default) is default


def test_missing_setting_without_default_returns_none(fake_config):
    assert config_access.setting("MISSING_SETTING") is None


def test_missing_config_module_returns_default_without_reading_config(monkeypatch):
    monkeypatch.delattr(config, "config_settings", raising=False)
    monkeypatch.setitem(sys.modules, "config.config_settings", None)
    default = object()
    assert config_access.setting("MISSING_SETTING", default) is default
    assert config_access.setting("MISSING_SETTING") is None


@pytest.mark.parametrize("relative", ["synthetic/report.csv", Path("synthetic/report.csv")])
def test_relative_project_path_uses_repo_root_from_any_cwd(tmp_path, monkeypatch, relative):
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[1]
    assert config_access.project_path(relative) == str(root / relative)


def test_absolute_project_path_passes_through(tmp_path):
    absolute = tmp_path / "synthetic.csv"
    assert config_access.project_path(absolute) == str(absolute)
    assert config_access.project_path(str(absolute)) == str(absolute)
