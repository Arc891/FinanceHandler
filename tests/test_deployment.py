"""
Tests for Phase 4 step 2: the example config and run.sh after the cutover.

The example config drops the keys the multi-month upload retired (plan
4.10) except the three step 6 removes once the Pi runs on OAuth
(GOOGLE_AUTH_MODE, GSHEET_NAME, GOOGLE_CREDENTIALS_PATH), and exports only
what it defines. run.sh refuses to deploy without the OAuth token, no longer
looks for the service account key, mounts src/config read-only so a setting
change needs a restart rather than a rebuild, and warns before
--force-rebuild prunes what could be the rollback image.
"""

import importlib.util
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RETIRED = ("GSHEET_TAB", "GSHEET_EXPENSE_START_ROW", "GSHEET_INCOME_START_ROW", "APPROVAL_CHANNEL_ID",
           "APPROVAL_WEBHOOK_URL", "PENDING_APPROVALS_FILE", "SESSION_DIR", "CLAUDE_MODEL")
UNTIL_STEP_6 = ("GOOGLE_AUTH_MODE", "GSHEET_NAME", "GOOGLE_CREDENTIALS_PATH")


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
    assert all(hasattr(mod, k) for k in UNTIL_STEP_6)


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
