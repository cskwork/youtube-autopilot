#!/usr/bin/env python3
"""Upload a video to YouTube as a PRIVATE draft by driving YouTube Studio.

Browser-only path (no OAuth client, no API key): attaches to the user's
logged-in Chrome via the Playwright agent CLI, opens the Studio upload dialog,
injects the file with setInputFiles, sets title/description, marks it
not-made-for-kids, advances the wizard, sets visibility, and saves the draft.

Use this when the channel account differs from any GCP project account (so the
Data API path in upload_youtube.py is impractical). The only later human step is
flipping the private draft to public.

Prints exactly one JSON object to stdout; logs go to stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "js" / "studio_upload.tmpl.js"
PRIVACY_RADIO = {"private": "PRIVATE", "unlisted": "UNLISTED", "public": "PUBLIC"}


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def cli_base(args: argparse.Namespace) -> list[str]:
    return shlex.split(args.cli)


def cmd(args: argparse.Namespace, *parts: str) -> list[str]:
    return [*cli_base(args), f"-s={args.session}", *parts]


def run(args: argparse.Namespace, parts: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if args.npm_cache:
        env["npm_config_cache"] = args.npm_cache
    return subprocess.run(parts, env=env, capture_output=True, text=True)


def upload_url(args: argparse.Namespace) -> str:
    if args.upload_url:
        return args.upload_url
    base = args.channel_url.rstrip("/")
    return f"{base}/videos/upload?d=ud"


def resolve_meta(args: argparse.Namespace) -> tuple[str, str]:
    """Return (title, description) from explicit flags or a script JSON."""
    title, desc = args.title or "", args.description or ""
    if (not title or not desc) and args.script_json:
        data = json.loads(Path(args.script_json).expanduser().read_text(encoding="utf-8"))
        yt = data.get("youtube", {}) if isinstance(data, dict) else {}
        title = title or str(yt.get("title", "")).strip()
        desc = desc or str(yt.get("description", ""))
    if not title:
        raise SystemExit("a title is required (via --title or --script-json youtube.title)")
    extra = (args.extra_description or "").strip()
    if extra:
        desc = f"{desc.rstrip()}\n\n{extra}" if desc.strip() else extra
    return title, desc


def render_template(video: Path, title: str, desc: str, privacy: str) -> str:
    tmpl = TEMPLATE.read_text(encoding="utf-8")
    return (
        tmpl.replace("__VIDEO__", json.dumps(str(video)))
        .replace("__TITLE__", json.dumps(title, ensure_ascii=False))
        .replace("__DESC__", json.dumps(desc, ensure_ascii=False))
        .replace("__PRIVACY__", json.dumps(PRIVACY_RADIO[privacy]))
    )


def parse_result(stdout: str | None, stderr: str | None) -> dict:
    out = (stdout or "").strip().strip('"').encode().decode("unicode_escape")
    try:
        return json.loads(out)
    except Exception:
        return {"ok": False, "rawstdout": stdout, "stderr": stderr}


def open_dialog(args: argparse.Namespace) -> None:
    run(args, cmd(args, "goto", upload_url(args)))
    time.sleep(args.settle)


def submit_upload(args: argparse.Namespace, js: str, out: Path) -> dict:
    gen = out.parent / "_studio_upload.run.js"
    gen.parent.mkdir(parents=True, exist_ok=True)
    gen.write_text(js, encoding="utf-8")
    proc = run(args, cmd(args, "run-code", "--filename", str(gen), "--raw"))
    gen.unlink(missing_ok=True)
    return parse_result(proc.stdout, proc.stderr)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in", dest="video", required=True, help="video file to upload")
    p.add_argument("--title", help="explicit title (else from --script-json)")
    p.add_argument("--description", help="explicit description (else from --script-json)")
    p.add_argument("--extra-description", default="",
                   help="text appended to the description (e.g. BGM attribution)")
    p.add_argument("--script-json", help="JSON with youtube.title/description")
    p.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    p.add_argument("--channel-url", default="https://studio.youtube.com/channel/UCkYZel8a-aj1BJdj6pYDr5w",
                   help="Studio channel base URL")
    p.add_argument("--upload-url", default="", help="override the full upload dialog URL")
    p.add_argument("--cli", default="npx @playwright/cli@latest")
    p.add_argument("--npm-cache", default="", help="empty = system cache so the CLI matches the attached session")
    p.add_argument("--session", default="vya")
    p.add_argument("--settle", type=int, default=7, help="seconds to wait after opening the dialog")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"video not found: {video}")
    if not TEMPLATE.is_file():
        raise SystemExit(f"missing template: {TEMPLATE}")
    title, desc = resolve_meta(args)
    log(f"[studio-upload] {video.name} -> {args.privacy} draft; title={title!r}")
    open_dialog(args)
    result = submit_upload(args, render_template(video, title, desc, args.privacy), video)
    if not result.get("ok"):
        raise SystemExit(f"studio upload failed: {result}")
    log(f"[studio-upload] steps: {result.get('log')}")
    print(json.dumps({"ok": True, "privacy": args.privacy, "title": title,
                      "steps": result.get("log", [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
