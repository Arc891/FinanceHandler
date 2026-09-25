#!/usr/bin/env python3
"""
Create the bot's Google OAuth token, once, on the workstation (plan 4.2).

Run it in your own terminal, not through a Claude session, so the token never
lands in a conversation:

    venv/bin/python scripts/google_login.py

It prints a URL. Paste the **whole** URL into a private/incognito window of the
Windows browser and sign in with the account that owns the Financiën folder.
Google shows "Google hasn't verified this app": Advanced > Go to Finance Bot.
The consent screen has one checkbox per scope: tick **both**.

Why these arguments: the library default port 8080 is taken on this machine,
WSL cannot open the Windows browser, and a first attempt on ``localhost`` in an
already signed-in browser failed with "Error 400: invalid_request". So the
flow listens on 127.0.0.1 with a free port and opens no browser.

The token is refused unless the granted scopes are exactly ``spreadsheets`` and
``drive.file``. It is written with mode 0600 to GOOGLE_OAUTH_TOKEN_PATH
(default data/google/authorized_user.json).
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from finance_core.config_access import project_path, setting  # noqa: E402
from finance_core.google_auth import (DEFAULT_CLIENT_PATH, DEFAULT_TOKEN_PATH,  # noqa: E402
                                      SCOPES, save_token, scope_problems)

REQUESTED_SCOPES = list(SCOPES)
PI_HOST = "rp5"
PI_DATA_DIR = "/home/pi/Coding/FinanceAutomation/data/google/"

PROMPT = ("\nOpen this URL in a PRIVATE/INCOGNITO browser window (copy all of it):\n\n{url}\n\n"
          "Tick BOTH checkboxes on the consent screen. Waiting for the browser...\n")


def _default_flow_factory(client_path, scopes):
    from google_auth_oauthlib.flow import InstalledAppFlow
    return InstalledAppFlow.from_client_secrets_file(client_path, scopes=scopes)


def main(argv=None, *, flow_factory=_default_flow_factory, stdout_write=sys.stdout.write) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--client", default=project_path(
        setting("GOOGLE_OAUTH_CLIENT_PATH", DEFAULT_CLIENT_PATH)))
    parser.add_argument("--token", default=project_path(
        setting("GOOGLE_OAUTH_TOKEN_PATH", DEFAULT_TOKEN_PATH)))
    args = parser.parse_args(argv)

    def say(line=""):
        stdout_write(line + "\n")

    if not os.path.exists(args.client):
        say(f"OAuth client file not found: {args.client}")
        say("Download the Desktop client JSON from Google Cloud > Credentials to that path.")
        return 1

    # Let oauthlib hand back a token whose scopes differ from the request, so
    # the check below can say which box was left unticked instead of crashing.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    flow = flow_factory(args.client, REQUESTED_SCOPES)
    creds = flow.run_local_server(host="127.0.0.1", port=0, open_browser=False,
                                  authorization_prompt_message=PROMPT, prompt="consent")

    granted = creds.granted_scopes if creds.granted_scopes is not None else creds.scopes
    problems = scope_problems(granted)
    if problems:
        say("Token NOT saved:")
        for problem in problems:
            say(f"  - {problem}")
        say("Run this script again and tick both checkboxes.")
        return 2
    if not creds.refresh_token:
        say("Token NOT saved: Google returned no refresh token. Remove the app's access at "
            "myaccount.google.com/permissions and run this script again.")
        return 2

    save_token(args.token, creds)
    say(f"Token saved to {args.token} (mode 0600), scopes: spreadsheets + drive.file.")
    say("Copy it to the Pi:")
    say(f"  scp {args.token} {PI_HOST}:{PI_DATA_DIR}")
    say(f"  ssh {PI_HOST} chmod 600 {PI_DATA_DIR}authorized_user.json")
    say("Reminder: the OAuth app must stay In production; in Testing Google expires the "
        "refresh token after 7 days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
