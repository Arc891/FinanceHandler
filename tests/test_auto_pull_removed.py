"""The abandoned bank auto-pull stays removed; manual upload and AI remain."""

import ast
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
REMOVED_NAMES = (
    "bank_scraper", "ASNBankScraper", "automation_endpoints",
    "playwright", "fastapi", "uvicorn",
)
REMOVED_PREFIXES = ("BANK_", "ASN_", "AUTO_DOWNLOAD_", "API_")
EXAMPLE = ROOT / "src/config/config_settings.example.py"


def code_lines(path):
    """Code without comments or module, class and function docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and ast.get_docstring(node):
            node.body.pop(0)
    return ast.unparse(tree).splitlines()


@pytest.mark.parametrize("path", [
    "src/api", "src/automation/bank_scraper.py", "scripts/browsercode",
    "docs/automation/AUTOMATION_PLAN.md",
    "docs/automation/BROWSERCODE_STATUS.md",
])
def test_auto_pull_paths_are_gone(path):
    assert not (ROOT / path).exists(), path


def test_no_source_line_uses_a_removed_name():
    hits = []
    for folder in ("src", "scripts"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            # Never inspect the owner's private settings, even in a full checkout.
            if path == ROOT / "src/config/config_settings.py" or path.is_symlink():
                continue
            if any(name in line for line in code_lines(path)
                   for name in REMOVED_NAMES):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == []


@pytest.mark.parametrize("dependency", ["playwright", "fastapi", "uvicorn"])
def test_auto_pull_dependencies_are_gone(dependency):
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert not re.search(rf"^\s*{dependency}(?=[<>=!~\[;\s]|$)",
                         requirements, re.MULTILINE | re.IGNORECASE)


def test_pydantic_floor_stays_with_ai_dependencies():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "# Bank Automation (Session 1)" not in requirements
    ai_section = requirements.split("# AI Categorization (Session 2)\n", 1)[1]
    ai_section = ai_section.split("\n#", 1)[0]
    assert "pydantic>=2.5.0" in ai_section.splitlines()
    assert "anthropic>=0.8.0" in ai_section.splitlines()


def test_example_assigns_no_auto_pull_settings():
    tree = ast.parse(EXAMPLE.read_text(encoding="utf-8"))
    assigned = {node.id for node in ast.walk(tree)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
    assert not {name for name in assigned if name.startswith(REMOVED_PREFIXES)}


def test_example_exports_no_auto_pull_settings():
    tree = ast.parse(EXAMPLE.read_text(encoding="utf-8"))
    exports = next(node.value for node in tree.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "__all__"
                           for target in node.targets))
    assert not {name for name in ast.literal_eval(exports)
                if name.startswith(REMOVED_PREFIXES)}


def test_example_removes_bank_directories_and_keeps_upload_directory():
    tree = ast.parse(EXAMPLE.read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not names & {"_bank_download_path", "_bank_session_dir"}
    calls = {ast.unparse(node) for node in ast.walk(tree)
             if isinstance(node, ast.Call)}
    assert "os.makedirs(_upload_path, exist_ok=True)" in calls
