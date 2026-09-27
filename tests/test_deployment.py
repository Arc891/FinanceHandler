"""
Tests for Phase 4 steps 2 and 6: the example config and run.sh after the cutover.

The example config drops every key the multi-month upload retired (plan
4.10), including the three step 6 removes once the Pi runs on OAuth
(GOOGLE_AUTH_MODE, GSHEET_NAME, GOOGLE_CREDENTIALS_PATH), and exports only
what it defines. The self-check requires none of them and no code reads them. run.sh refuses to deploy without the OAuth token, no longer
looks for the service account key, mounts src/config read-only so a setting
change needs a restart rather than a rebuild, and warns before
--force-rebuild prunes what could be the rollback image.
"""

import importlib.util
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RETIRED = ("GSHEET_TAB", "GSHEET_EXPENSE_START_ROW", "GSHEET_INCOME_START_ROW", "APPROVAL_CHANNEL_ID",
           "APPROVAL_WEBHOOK_URL", "PENDING_APPROVALS_FILE", "SESSION_DIR", "CLAUDE_MODEL",
           "GOOGLE_AUTH_MODE", "GSHEET_NAME", "GOOGLE_CREDENTIALS_PATH")


def example():
    path = os.path.join(ROOT, "src", "config", "config_settings.example.py")
    spec = importlib.util.spec_from_file_location("example_cfg", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_sh():
    with open(os.path.join(ROOT, "run.sh"), encoding="utf-8") as f:
        return f.read()


def test_the_example_config_no_longer_holds_the_retired_keys():
    mod = example()
    assert [k for k in RETIRED if hasattr(mod, k)] == []


def test_the_self_check_requires_no_retired_key():
    from config_check import REQUIRED_SETTINGS
    assert not set(RETIRED) & set(REQUIRED_SETTINGS)


def test_no_code_reads_a_retired_key():
    # src/config/ is skipped: it holds the private config and the example
    # (checked above); the tests name the keys to assert they are gone
    pattern = re.compile(r"\b(%s)\b" % "|".join(RETIRED))
    hits = []
    for top in ("src", "scripts"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, top)):
            dirnames[:] = [d for d in dirnames if d not in ("config", "__pycache__")]
            for name in filenames:
                if name.endswith((".py", ".sh")):
                    path = os.path.join(dirpath, name)
                    with open(path, encoding="utf-8") as f:
                        if pattern.search(f.read()):
                            hits.append(os.path.relpath(path, ROOT))
    assert hits == []


def test_the_example_exports_only_what_it_defines():
    mod = example()
    assert [k for k in mod.__all__ if not hasattr(mod, k)] == []
    assert not set(RETIRED) & set(mod.__all__)


def test_run_sh_refuses_to_deploy_without_the_oauth_token():
    text = run_sh()
    check = re.search(r'if \[\[ ! -f "data/google/authorized_user\.json" \]\]; then(.*?)fi', text, re.S)
    assert check and "exit 1" in check[1] and "google_login.py" in check[1]


def test_run_sh_no_longer_looks_for_the_service_account_key():
    assert "google_service_account.json" not in run_sh()


def test_run_sh_mounts_the_config_read_only():
    assert '-v "$(pwd)/src/config:/app/src/config:ro"' in run_sh()


def test_force_rebuild_warns_that_the_prune_can_remove_the_rollback_image():
    text = run_sh()
    block = text[text.index("if [[ $FORCE_REBUILD -eq 1 ]]; then"):]
    block = block[:block.index("fi\n")]
    assert "docker tag" in block and block.index("docker tag") < block.index("docker system prune")
    assert "data/" in block        # the bind-mounted data survives the prune
