"""
Tests for finance_core.google_auth (plan 4.2) and scripts/google_login.py.
"""

import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest
from google.auth.exceptions import RefreshError

from finance_core import google_auth
from finance_core.google_auth import (DRIVE_FILE_SCOPE, SCOPES, SPREADSHEETS_SCOPE,
                                      GoogleAuthError, check_scopes, get_credentials)

import google_login


def _utcnow():
    # google-auth compares expiry as naive UTC
    return datetime.now(timezone.utc).replace(tzinfo=None)


def token_info(scopes=SCOPES, expired=True, refresh_token="rt-1"):
    expiry = _utcnow() + (timedelta(hours=-1) if expired else timedelta(hours=1))
    return {
        "token": "at-0",
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid.apps.googleusercontent.com",
        "client_secret": "secret",
        "scopes": list(scopes),
        "expiry": expiry.isoformat() + "Z",
    }


def write_token(path, **kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token_info(**kwargs)))
    return path


@pytest.fixture
def refresh_ok(monkeypatch):
    """Replace the network refresh with one that issues a new token and rotates the refresh token."""
    calls = []

    def fake_refresh(self, request):
        calls.append(request)
        self.token = "at-1"
        self._refresh_token = "rt-2"
        self.expiry = _utcnow() + timedelta(hours=1)

    monkeypatch.setattr(google_auth.OAuthCredentials, "refresh", fake_refresh)
    return calls


# ── scopes ────────────────────────────────────────────────────────────────────

def test_scopes_are_exactly_spreadsheets_and_drive_file():
    assert set(SCOPES) == {
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    }


def test_no_restricted_drive_scope_is_requested():
    # Every drive.* scope except drive.file is restricted and costs a CASA audit (plan 4.2).
    drive = [s for s in SCOPES if "/auth/drive" in s]
    assert drive == ["https://www.googleapis.com/auth/drive.file"]
    assert google_login.REQUESTED_SCOPES == list(SCOPES)


def test_check_scopes_names_the_unticked_box():
    with pytest.raises(GoogleAuthError, match="drive.file"):
        check_scopes([SPREADSHEETS_SCOPE])
    with pytest.raises(GoogleAuthError, match="spreadsheets"):
        check_scopes([DRIVE_FILE_SCOPE])


def test_check_scopes_refuses_an_extra_scope():
    with pytest.raises(GoogleAuthError, match="drive.readonly"):
        check_scopes(list(SCOPES) + ["https://www.googleapis.com/auth/drive.readonly"])


def test_check_scopes_accepts_exactly_the_two():
    check_scopes([DRIVE_FILE_SCOPE, SPREADSHEETS_SCOPE])


# ── get_credentials ──────────────────────────────────────────────────────────

def test_missing_token_names_the_login_script(tmp_path):
    with pytest.raises(GoogleAuthError, match="google_login.py"):
        get_credentials(tmp_path / "authorized_user.json", mode="oauth")


def test_refresh_error_is_a_google_auth_error_naming_the_login_script(tmp_path, monkeypatch):
    path = write_token(tmp_path / "authorized_user.json")

    def boom(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(google_auth.OAuthCredentials, "refresh", boom)
    with pytest.raises(GoogleAuthError, match="google_login.py"):
        get_credentials(path, mode="oauth")


def test_refreshed_credentials_are_written_back(tmp_path, refresh_ok):
    path = write_token(tmp_path / "authorized_user.json")
    creds = get_credentials(path, mode="oauth")
    assert creds.token == "at-1"
    saved = json.loads(path.read_text())
    assert saved["token"] == "at-1"
    assert saved["refresh_token"] == "rt-2"      # Google may rotate it
    assert set(saved["scopes"]) == set(SCOPES)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert len(refresh_ok) == 1


def test_valid_token_is_not_refreshed_or_rewritten(tmp_path, refresh_ok):
    path = write_token(tmp_path / "authorized_user.json", expired=False)
    before = path.read_text()
    get_credentials(path, mode="oauth")
    assert refresh_ok == []
    assert path.read_text() == before


def test_token_missing_a_scope_is_refused_on_load(tmp_path, refresh_ok):
    path = write_token(tmp_path / "authorized_user.json", scopes=[SPREADSHEETS_SCOPE])
    with pytest.raises(GoogleAuthError, match="drive.file"):
        get_credentials(path, mode="oauth")
    assert refresh_ok == []


def test_token_without_refresh_token_is_refused(tmp_path, refresh_ok):
    path = write_token(tmp_path / "authorized_user.json", refresh_token=None)
    with pytest.raises(GoogleAuthError, match="google_login.py"):
        get_credentials(path, mode="oauth")


def test_unknown_mode_is_refused(tmp_path):
    with pytest.raises(GoogleAuthError, match="GOOGLE_AUTH_MODE"):
        get_credentials(tmp_path / "x.json", mode="apikey")


def test_service_account_mode_still_builds_a_client(tmp_path, monkeypatch):
    built = {}

    def fake_from_file(path, scopes):
        built["path"], built["scopes"] = path, scopes
        return "sa-creds"

    monkeypatch.setattr(google_auth.ServiceAccountCredentials, "from_service_account_file",
                        staticmethod(fake_from_file))
    key = tmp_path / "sa.json"
    key.write_text("{}")
    assert google_auth.get_credentials(mode="service_account", service_account_path=key) == "sa-creds"
    assert built["path"] == str(key)
    assert list(built["scopes"]) == list(SCOPES)


def test_gspread_client_uses_the_shared_credentials(monkeypatch):
    seen = {}
    monkeypatch.setattr(google_auth.gspread, "authorize", lambda creds: seen.setdefault("c", creds))
    assert google_auth.get_gspread_client(credentials="creds") == "creds"


# ── scripts/google_login.py ──────────────────────────────────────────────────

class FakeCreds:
    def __init__(self, granted, refresh_token="rt"):
        self.granted_scopes = granted
        self.scopes = list(SCOPES)
        self.refresh_token = refresh_token

    def to_json(self):
        return json.dumps({"refresh_token": self.refresh_token, "scopes": self.scopes})


class FakeFlow:
    def __init__(self, creds):
        self.creds = creds
        self.kwargs = None

    def run_local_server(self, **kwargs):
        self.kwargs = kwargs
        return self.creds


def run_login(tmp_path, creds):
    client = tmp_path / "oauth_client.json"
    client.write_text("{}")
    token = tmp_path / "google" / "authorized_user.json"
    flow = FakeFlow(creds)
    made = {}

    def factory(path, scopes):
        made["path"], made["scopes"] = path, scopes
        return flow

    out = []
    code = google_login.main(["--client", str(client), "--token", str(token)],
                             flow_factory=factory, stdout_write=out.append)
    return code, token, flow, made, "".join(out)


def test_login_uses_loopback_ip_and_a_free_port_and_no_browser(tmp_path):
    code, _, flow, made, _ = run_login(tmp_path, FakeCreds(list(SCOPES)))
    assert code == 0
    assert flow.kwargs["host"] == "127.0.0.1"
    assert flow.kwargs["port"] == 0
    assert flow.kwargs["open_browser"] is False
    assert made["scopes"] == list(SCOPES)


def test_login_saves_token_0600_and_prints_the_scp_line(tmp_path):
    code, token, _, _, out = run_login(tmp_path, FakeCreds(list(SCOPES)))
    assert code == 0
    assert stat.S_IMODE(os.stat(token).st_mode) == 0o600
    assert "scp" in out and "rp5" in out
    assert "In production" in out


def test_login_refuses_a_token_missing_drive_file(tmp_path):
    code, token, _, _, out = run_login(tmp_path, FakeCreds([SPREADSHEETS_SCOPE]))
    assert code != 0
    assert not token.exists()
    assert "drive.file" in out


def test_login_refuses_a_token_missing_spreadsheets(tmp_path):
    code, token, _, _, out = run_login(tmp_path, FakeCreds([DRIVE_FILE_SCOPE]))
    assert code != 0
    assert not token.exists()
    assert "spreadsheets" in out


def test_login_refuses_a_token_without_refresh_token(tmp_path):
    code, token, _, _, out = run_login(tmp_path, FakeCreds(list(SCOPES), refresh_token=None))
    assert code != 0
    assert not token.exists()


def test_login_with_missing_client_file_fails_cleanly(tmp_path):
    out = []
    code = google_login.main(["--client", str(tmp_path / "nope.json"),
                              "--token", str(tmp_path / "t.json")],
                             flow_factory=lambda *a, **k: None, stdout_write=out.append)
    assert code != 0
    assert "oauth_client" in "".join(out) or "nope.json" in "".join(out)
