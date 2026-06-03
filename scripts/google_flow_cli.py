#!/usr/bin/env python3
"""Generate a Google Flow video by driving a logged-in Chrome session.

Flow: attach (CDP/extension) -> select/open a Google Flow project tab ->
set Video mode -> optional reference image -> prompt -> Generate -> poll for
the resulting <video> -> download the MP4 via the browser context request.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
JS = HERE / "js"


def cli_base(args: argparse.Namespace) -> list[str]:
    return shlex.split(args.cli)


def cmd(args: argparse.Namespace, *parts: str, session: bool = True) -> list[str]:
    base = cli_base(args)
    if session:
        base.append(f"-s={args.session}")
    return [*base, *parts]


def run(
    args: argparse.Namespace,
    parts: list[str],
    capture: bool = False,
    raw_out: Path | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if args.npm_cache:
        env["npm_config_cache"] = args.npm_cache
    if raw_out is not None:
        with raw_out.open("wb") as fh:
            return subprocess.run(parts, env=env, stdout=fh, stderr=subprocess.PIPE)
    return subprocess.run(parts, env=env, capture_output=capture, text=True)


def attach(args: argparse.Namespace) -> None:
    if args.attach == "extension":
        channel = args.extension_channel or "chrome"
        target = f"--extension={channel}"
    else:
        target = f"--cdp={args.cdp_endpoint}"
    proc = run(args, [*cli_base(args), "attach", target, f"--session={args.session}"], capture=True)
    sys.stderr.write(proc.stdout or "")
    if proc.returncode != 0:
        raise SystemExit(f"attach failed: {proc.stderr or proc.stdout}")


def select_flow_tab(args: argparse.Namespace) -> None:
    proc = run(args, cmd(args, "tab-list"), capture=True)
    idx = _find_flow_tab((proc.stdout or "").splitlines())
    if idx is None:
        run(args, cmd(args, "tab-new", args.app_url), capture=True)
    else:
        run(args, cmd(args, "tab-select", idx), capture=True)
    href = run(args, cmd(args, "eval", '"location.href"'), capture=True).stdout or ""
    if not _is_flow_url(href):
        run(args, cmd(args, "goto", args.app_url), capture=True)


def _find_flow_tab(lines: list[str]) -> str | None:
    for line in lines:
        if not _is_flow_url(line):
            continue
        head = line.strip().lstrip("- ").split(":", 1)[0].strip()
        if head.isdigit():
            return head
    return None


def _is_flow_url(text: str) -> bool:
    lower = text.lower()
    return ("labs.google" in lower or "flow.google" in lower) and "flow" in lower


def compose_and_submit(args: argparse.Namespace) -> dict:
    tmpl = (JS / "flow_compose.tmpl.js").read_text(encoding="utf-8")
    images = [str(Path(image).resolve()) for image in args.images]
    js = (
        tmpl.replace("__PROMPT__", json.dumps(args.prompt, ensure_ascii=False))
        .replace("__IMAGES__", json.dumps(images, ensure_ascii=False))
        .replace("__ASPECT_RATIO__", json.dumps(args.aspect_ratio))
        .replace("__DURATION__", json.dumps(args.duration))
    )
    gen = Path(args.out).resolve().parent / "_flow_compose.run.js"
    gen.parent.mkdir(parents=True, exist_ok=True)
    gen.write_text(js, encoding="utf-8")
    proc = run(args, cmd(args, "run-code", "--filename", str(gen), "--raw"), capture=True)
    return _json_result(proc.stdout, proc.stderr)


def _json_result(stdout: str | None, stderr: str | None) -> dict:
    out = (stdout or "").strip().strip('"').encode().decode("unicode_escape")
    try:
        return json.loads(out)
    except Exception:
        return {"ok": False, "rawstdout": stdout, "stderr": stderr}


def poll_status(args: argparse.Namespace) -> dict:
    proc = run(
        args,
        cmd(args, "run-code", "--filename", str(JS / "flow_status.js"), "--raw"),
        capture=True,
    )
    return _json_result(proc.stdout, proc.stderr)


def wait_for_video(args: argparse.Namespace, previous_sources: set[str] | None = None) -> dict:
    deadline = time.time() + args.timeout
    previous_sources = previous_sources or set()
    last = {}
    while time.time() < deadline:
        status = poll_status(args)
        last = status or last
        sys.stderr.write(f"[poll] {json.dumps(status, ensure_ascii=False)}\n")
        if _video_ready(status, previous_sources):
            status["src"] = _new_video_src(status, previous_sources)
            return status
        time.sleep(args.poll_interval)
    raise SystemExit(f"timed out after {args.timeout}s waiting for video; last={last}")


def _video_sources(status: dict | None) -> set[str]:
    if not status:
        return set()
    sources = status.get("video_srcs") or []
    if status.get("src"):
        sources = [*sources, status["src"]]
    return {src for src in sources if src}


def _new_video_src(status: dict | None, previous_sources: set[str]) -> str:
    if not status:
        return ""
    # Flow lists clips NEWEST-FIRST, so the just-rendered clip is the FIRST
    # source that was not already present before this submit. The old code
    # iterated reversed() (oldest-first) and trusted status['src'], so on a
    # project with pre-existing clips it grabbed a STALE/older tile instead of
    # the new render (the businessman-instead-of-the-prompt bug).
    for src in status.get("video_srcs") or []:
        if src and src not in previous_sources:
            return src
    src = status.get("src")
    return src if src and src not in previous_sources else ""


def _video_ready(status: dict, previous_sources: set[str] | None = None) -> bool:
    previous_sources = previous_sources or set()
    return bool(
        status
        and not status.get("generating")
        and status.get("videos", 0) >= 1
        and status.get("dur", 0)
        and _new_video_src(status, previous_sources)
    )


def download(args: argparse.Namespace, src: str, edit_url: str = "") -> Path:
    out = Path(args.out).resolve()
    direct_error = _download_via_media_src(args, out, src)
    if direct_error is None:
        return out
    sys.stderr.write(f"[download] direct media fetch failed: {direct_error}\n")
    return _download_via_button(args, out, edit_url)


def _download_via_media_src(args: argparse.Namespace, out: Path, src: str) -> str | None:
    if not src:
        return "no new video source"
    raw = Path(args.out).resolve().parent / "_flow_download.b64"
    gen = out.parent / "_flow_download.run.js"
    gen.parent.mkdir(parents=True, exist_ok=True)
    gen.write_text(_download_js(src), encoding="utf-8")
    proc = run(
        args,
        cmd(args, "run-code", "--filename", str(gen), "--raw"),
        raw_out=raw,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="ignore") if proc.stderr else ""
        return f"download run-code failed: {err}"
    try:
        data = _read_base64(raw)
    except ValueError as exc:
        return str(exc)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    raw.unlink(missing_ok=True)
    gen.unlink(missing_ok=True)
    return None


def _download_js(src: str) -> str:
    return f"""// Generated by google_flow_cli.py; downloads the selected new video.
page => (async () => {{
  const src = {json.dumps(src)};
  const resp = await page.context().request.get(src);
  if (!resp.ok()) return 'ERR:http-' + resp.status();
  const buf = await resp.body();
  return buf.toString('base64');
}})()
"""


def _download_via_button(args: argparse.Namespace, out: Path, edit_url: str = "") -> Path:
    tmpl = (JS / "flow_download_button.tmpl.js").read_text(encoding="utf-8")
    js = (
        tmpl.replace("__OUT__", json.dumps(str(out), ensure_ascii=False))
        .replace("__EDIT_URL__", json.dumps(edit_url, ensure_ascii=False))
    )
    gen = out.parent / "_flow_download_button.run.js"
    gen.parent.mkdir(parents=True, exist_ok=True)
    gen.write_text(js, encoding="utf-8")
    proc = run(
        args,
        cmd(args, "run-code", "--filename", str(gen), "--raw"),
        capture=True,
    )
    result = _json_result(proc.stdout, proc.stderr)
    if proc.returncode != 0 or not result.get("ok"):
        raise SystemExit(f"download button failed: {result}")
    if not out.exists() or out.stat().st_size == 0:
        raise SystemExit(f"download button wrote no video: {out}")
    return out


def _read_base64(path: Path) -> bytes:
    data = path.read_bytes().strip()
    if data[:1] == b'"' and data[-1:] == b'"':
        data = data[1:-1]
    if data.startswith(b"ERR:"):
        raise ValueError(f"download error: {data.decode(errors='ignore')}")
    mp4 = base64.b64decode(data)
    if mp4[4:8] != b"ftyp":
        raise ValueError(f"downloaded bytes are not an MP4 (magic={mp4[4:12]!r}, size={len(mp4)})")
    return mp4


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prompt", required=True, help="video description")
    p.add_argument(
        "--image",
        action="append",
        default=[],
        dest="images",
        help="optional first-frame or ingredient image; repeat for multiple images",
    )
    p.add_argument("--out", default="flow_out.mp4", help="output MP4 path")
    p.add_argument("--cli", default="npx @playwright/cli@latest")
    # Empty = system npm cache, so this CLI install matches the attached session.
    p.add_argument("--npm-cache", default="")
    p.add_argument("--session", default="flow")
    p.add_argument("--attach", choices=["cdp", "extension"], default="cdp")
    p.add_argument("--cdp-endpoint", default="chrome")
    p.add_argument("--extension-channel", default="chrome")
    p.add_argument("--app-url", default="https://labs.google/fx/ko/tools/flow")
    p.add_argument("--aspect-ratio", default="16:9")
    p.add_argument("--duration", type=int, default=8)
    p.add_argument("--timeout", type=int, default=420)
    p.add_argument("--poll-interval", type=int, default=15)
    p.add_argument("--no-attach", action="store_true")
    p.add_argument("--fresh", action="store_true", help="reload the Flow project before composing")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.no_attach:
        attach(args)
    select_flow_tab(args)
    if args.fresh:
        run(args, cmd(args, "goto", args.app_url), capture=True)
        time.sleep(2)
    baseline = poll_status(args)
    previous_sources = _video_sources(baseline)
    result = compose_and_submit(args)
    sys.stderr.write(f"[compose] {json.dumps(result, ensure_ascii=False)}\n")
    if not result.get("ok"):
        raise SystemExit(f"compose/submit failed: {result}")
    status = wait_for_video(args, previous_sources)
    out = download(args, status["src"], status.get("url", ""))
    print(
        json.dumps(
            {"ok": True, "out": str(out), "bytes": out.stat().st_size},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
