#!/usr/bin/env python3
"""Stage 7: upload the rendered video to YouTube as a PRIVATE draft.

Uses the YouTube Data API v3 (videos.insert, resumable upload). Metadata is
taken from a script JSON (youtube.title/description/tags/category) or from
explicit --title/--description/--tags/--category flags. The token is loaded
from --token; if missing/invalid the OAuth consent runs once (unless --dry-run)
and the refreshed token is re-cached.

The ONLY later human step is flipping private->public in YouTube Studio; this
script stops at the private draft. On success prints exactly one JSON object to
stdout. All progress/log lines go to stderr. Never prints token/secret content.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
DEFAULT_TOKEN = os.path.expanduser("~/.config/vimax-youtube-autopilot/token.json")
DEFAULT_CATEGORY = "22"  # People & Blogs


@dataclass(frozen=True)
class VideoMetadata:
    """Resolved snippet/status fields for videos.insert."""

    title: str
    description: str
    tags: list[str]
    category_id: str
    privacy: str
    made_for_kids: bool


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the uploader."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="video", required=True, help="video file to upload")
    parser.add_argument("--script-json", help="JSON with youtube.title/description/tags/category")
    parser.add_argument("--title", help="explicit title (overrides script JSON)")
    parser.add_argument("--description", help="explicit description (overrides script JSON)")
    parser.add_argument("--tags", help="explicit comma-separated tags (overrides script JSON)")
    parser.add_argument("--category", help="explicit numeric category id (overrides script JSON)")
    parser.add_argument(
        "--privacy",
        choices=["private", "unlisted", "public"],
        default="private",
        help="privacy status (default private)",
    )
    kids = parser.add_mutually_exclusive_group()
    kids.add_argument("--made-for-kids", dest="made_for_kids", action="store_true")
    kids.add_argument("--not-made-for-kids", dest="made_for_kids", action="store_false")
    parser.set_defaults(made_for_kids=False)
    parser.add_argument("--client-secret", help="OAuth client_secret JSON path")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="token cache path")
    parser.add_argument("--dry-run", action="store_true", help="validate only; do not upload")
    return parser.parse_args()


def load_script_meta(script_json: Path | None) -> dict[str, object]:
    """Return the youtube.* sub-object from the script JSON, or an empty dict."""
    if script_json is None:
        return {}
    if not script_json.is_file():
        raise SystemExit(f"script JSON not found: {script_json}")
    try:
        data = json.loads(script_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid script JSON {script_json}: {exc}") from exc
    section = data.get("youtube", data)
    return section if isinstance(section, dict) else {}


def _coerce_tags(raw: object) -> list[str]:
    """Normalize a tags value (list or comma string) into a clean string list."""
    if isinstance(raw, list):
        items = [str(t) for t in raw]
    elif isinstance(raw, str):
        items = raw.split(",")
    else:
        return []
    return [t.strip() for t in items if t.strip()]


def resolve_metadata(args: argparse.Namespace) -> VideoMetadata:
    """Merge explicit flags over script JSON into a validated VideoMetadata."""
    meta = load_script_meta(Path(args.script_json).expanduser() if args.script_json else None)
    title = args.title if args.title is not None else str(meta.get("title", "")).strip()
    if not title:
        raise SystemExit("title is required (via --title or script JSON youtube.title)")
    description = args.description if args.description is not None else str(meta.get("description", ""))
    tags = _coerce_tags(args.tags) if args.tags is not None else _coerce_tags(meta.get("tags"))
    category = args.category or str(meta.get("category", "") or "").strip() or DEFAULT_CATEGORY
    if not category.isdigit():
        raise SystemExit(f"category must be a numeric id, got: {category!r}")
    return VideoMetadata(
        title=title,
        description=description,
        tags=tags,
        category_id=category,
        privacy=args.privacy,
        made_for_kids=bool(args.made_for_kids),
    )


def _persist_token(creds: Credentials, token_path: Path) -> None:
    """Write refreshed credentials back to the cache (parents + 0600)."""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)


def _refresh_or_consent(creds: Credentials | None, client_secret: Path | None, token_path: Path) -> Credentials:
    """Refresh expired creds or run the consent flow when no valid token exists."""
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _persist_token(creds, token_path)
            return creds
        except google.auth.exceptions.RefreshError as exc:
            print(f"[auth] token refresh failed, re-running consent: {exc}", file=sys.stderr)
    if client_secret is None or not client_secret.is_file():
        raise SystemExit("no valid token and --client-secret missing; run get_youtube_token.py first")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    fresh = flow.run_local_server(port=0)
    _persist_token(fresh, token_path)
    return fresh


def load_credentials(token_path: Path, client_secret: Path | None) -> Credentials:
    """Load cached credentials, refreshing or re-consenting as needed."""
    creds: Credentials | None = None
    if token_path.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (ValueError, KeyError) as exc:
            print(f"[auth] cached token unreadable, re-authenticating: {exc}", file=sys.stderr)
            creds = None
    return _refresh_or_consent(creds, client_secret, token_path)


def _build_body(meta: VideoMetadata) -> dict[str, object]:
    """Construct the videos.insert request body from resolved metadata."""
    return {
        "snippet": {
            "title": meta.title,
            "description": meta.description,
            "tags": meta.tags,
            "categoryId": meta.category_id,
        },
        "status": {
            "privacyStatus": meta.privacy,
            "selfDeclaredMadeForKids": meta.made_for_kids,
        },
    }


def upload_video(creds: Credentials, video_path: Path, meta: VideoMetadata) -> str:
    """Run the resumable upload and return the created video id."""
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    media = MediaFileUpload(str(video_path), resumable=True, mimetype="video/*")
    request = youtube.videos().insert(part="snippet,status", body=_build_body(meta), media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status is not None:
            print(f"[upload] {int(status.progress() * 100)}%", file=sys.stderr)
    print("[upload] 100%", file=sys.stderr)
    video_id = response.get("id")
    if not video_id:
        raise SystemExit(f"upload succeeded but no video id returned: {response}")
    return str(video_id)


def _result(video_id: str, privacy: str) -> dict[str, object]:
    """Build the success result object for a completed upload."""
    return {
        "ok": True,
        "video_id": video_id,
        "watch_url": f"https://youtu.be/{video_id}",
        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "privacy": privacy,
    }


def _dry_run(video_path: Path, token_path: Path, client_secret: Path | None, meta: VideoMetadata) -> dict[str, object]:
    """Validate inputs without uploading and return the dry-run result."""
    token_ok = token_path.is_file()
    secret_ok = client_secret is not None and client_secret.is_file()
    if not token_ok and not secret_ok:
        raise SystemExit("dry-run: neither a cached token nor --client-secret is available")
    print(f"[dry-run] video ok ({video_path.stat().st_size} bytes), token={token_ok}, secret={secret_ok}", file=sys.stderr)
    return {
        "ok": True,
        "dry_run": True,
        "video": str(video_path),
        "title": meta.title,
        "tags": meta.tags,
        "category": meta.category_id,
        "privacy": meta.privacy,
        "made_for_kids": meta.made_for_kids,
        "token_present": token_ok,
        "client_secret_present": secret_ok,
    }


def main() -> int:
    """Entry point: resolve metadata, authenticate, upload, emit result JSON."""
    args = parse_args()
    video_path = Path(args.video).expanduser().resolve()
    if not video_path.is_file():
        raise SystemExit(f"input video not found: {video_path}")
    token_path = Path(args.token).expanduser()
    client_secret = Path(args.client_secret).expanduser().resolve() if args.client_secret else None
    meta = resolve_metadata(args)
    if args.dry_run:
        print(json.dumps(_dry_run(video_path, token_path, client_secret, meta), ensure_ascii=False))
        return 0
    print(f"[upload] authenticating ({token_path})", file=sys.stderr)
    creds = load_credentials(token_path, client_secret)
    video_id = upload_video(creds, video_path, meta)
    print(json.dumps(_result(video_id, meta.privacy), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
