#!/usr/bin/env python3
"""One-time helper: run the YouTube OAuth consent flow and cache the token.

Stage 7 setup for youtube-autopilot. Opens the InstalledAppFlow consent
in a browser once, then persists the resulting credentials (chmod 600) so the
uploader can run unattended afterwards.

On success prints exactly one JSON object to stdout: {"ok": true, "token": ...}.
All progress/log lines go to stderr. Never prints token contents.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
DEFAULT_TOKEN = os.path.expanduser("~/.config/youtube-autopilot/token.json")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the one-time consent helper."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-secret", required=True, help="OAuth client_secret JSON path")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="token cache output path")
    parser.add_argument("--port", type=int, default=0, help="local redirect server port (0 = auto)")
    return parser.parse_args()


def run_consent(client_secret: Path, port: int) -> str:
    """Run the installed-app consent flow and return the credentials JSON."""
    if not client_secret.is_file():
        raise SystemExit(f"client secret not found: {client_secret}")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=port)
    return creds.to_json()


def persist_token(token_json: str, token_path: Path) -> None:
    """Write the token to disk with parents created and 0600 permissions."""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token_json, encoding="utf-8")
    os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)


def main() -> int:
    """Entry point: obtain consent, cache the token, emit the result JSON."""
    args = parse_args()
    client_secret = Path(args.client_secret).expanduser().resolve()
    token_path = Path(args.token).expanduser()
    print(f"[consent] launching OAuth flow for {client_secret.name}", file=sys.stderr)
    token_json = run_consent(client_secret, args.port)
    persist_token(token_json, token_path)
    print(f"[consent] token cached at {token_path}", file=sys.stderr)
    print(json.dumps({"ok": True, "token": str(token_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
