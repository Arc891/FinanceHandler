"""
Google credentials for the bot (plan 4.2).

The bot runs on the user's own Google account through an OAuth token created
once on the workstation by scripts/google_login.py. The service account is
retired for runtime use: its Drive quota is 0, so it cannot create a month.

Scopes are exactly ``spreadsheets`` and ``drive.file``. Every other ``drive.*``
scope is restricted and would require a paid CASA security assessment, so none
may be added without a decision from the user. tests/test_google_auth.py fails
if one is.

GOOGLE_AUTH_MODE = "service_account" keeps the old key usable during Phases
1-3 only; it is removed in Phase 4.
"""

import json
import logging
import os
import tempfile

import gspread
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials

from finance_core.config_access import project_path, setting

logger = logging.getLogger(__name__)

SPREADSHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
SCOPES = (SPREADSHEETS_SCOPE, DRIVE_FILE_SCOPE)

# What each scope is called on Google's granular consent screen.
_SCOPE_BOXES = {
    SPREADSHEETS_SCOPE: "spreadsheets (\"See, edit, create and delete all your Google Sheets spreadsheets\")",
    DRIVE_FILE_SCOPE: "drive.file (\"See, edit, create and delete only the specific Google Drive files you use with this app\")",
}

DEFAULT_TOKEN_PATH = "data/google/authorized_user.json"
DEFAULT_CLIENT_PATH = "data/google/oauth_client.json"
LOGIN_HINT = ("run `venv/bin/python scripts/google_login.py` on the workstation "
              "and copy data/google/authorized_user.json to the Pi")


class GoogleAuthError(RuntimeError):
    """No usable Google credentials. The message says how to get them."""


def scope_problems(granted) -> list:
    """Human-readable reasons why ``granted`` is not exactly SCOPES; empty when it is."""
    granted = set(granted or ())
    problems = [f"missing scope {_SCOPE_BOXES[s]}: its checkbox was left unticked"
                for s in SCOPES if s not in granted]
    problems += [f"unexpected scope {s}: only spreadsheets and drive.file are allowed"
                 for s in sorted(granted - set(SCOPES))]
    return problems


def check_scopes(granted) -> None:
    problems = scope_problems(granted)
    if problems:
        raise GoogleAuthError("; ".join(problems) + f". Re-consent: {LOGIN_HINT}")


def token_path() -> str:
    return project_path(setting("GOOGLE_OAUTH_TOKEN_PATH", DEFAULT_TOKEN_PATH))


def save_token(path, credentials) -> None:
    """Write the token atomically with mode 0600."""
    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".token.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(credentials.to_json())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _load_oauth(path) -> OAuthCredentials:
    path = os.fspath(path)
    if not os.path.exists(path):
        raise GoogleAuthError(f"no Google token at {path}; {LOGIN_HINT}")
    try:
        with open(path, encoding="utf-8") as fh:
            info = json.load(fh)
        check_scopes(info.get("scopes"))
        return OAuthCredentials.from_authorized_user_info(info)
    except GoogleAuthError:
        raise
    except (ValueError, KeyError) as exc:
        raise GoogleAuthError(f"unreadable Google token at {path} ({exc}); {LOGIN_HINT}") from exc


def get_credentials(path=None, *, mode=None, service_account_path=None):
    """
    Credentials for every Google client the bot builds.

    OAuth mode loads the token, refreshes it when needed and writes it back
    after every refresh, because Google may rotate the refresh token. The bot
    never opens a browser: a missing or revoked token is a GoogleAuthError.
    """
    mode = mode or setting("GOOGLE_AUTH_MODE", "oauth")
    if mode == "service_account":
        key = service_account_path or project_path(
            setting("GOOGLE_CREDENTIALS_PATH", "src/config/google_service_account.json"))
        return ServiceAccountCredentials.from_service_account_file(os.fspath(key), scopes=SCOPES)
    if mode != "oauth":
        raise GoogleAuthError(f"unknown GOOGLE_AUTH_MODE {mode!r}: use 'oauth' or 'service_account'")

    path = path or token_path()
    creds = _load_oauth(path)
    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise GoogleAuthError(f"the Google token at {path} has no refresh token; {LOGIN_HINT}")
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        raise GoogleAuthError(f"refreshing the Google token failed ({exc}); {LOGIN_HINT}") from exc
    if creds.granted_scopes:
        check_scopes(creds.granted_scopes)
    save_token(path, creds)
    logger.info("Google token refreshed and saved")
    return creds


def get_gspread_client(credentials=None) -> gspread.Client:
    return gspread.authorize(credentials or get_credentials())


def get_sheets_service(credentials=None):
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=credentials or get_credentials(), cache_discovery=False)


def get_drive_service(credentials=None):
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=credentials or get_credentials(), cache_discovery=False)
