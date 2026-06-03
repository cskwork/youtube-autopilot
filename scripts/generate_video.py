#!/usr/bin/env python3
"""Stage 4 - generate the raw Flow video from a storyboard.

Reads ``flow_prompt`` from ``script.json``, seeds the vendored
``google_flow_cli.py`` with up to ``--max-images`` storyboard frames
(scene_*.png), runs it as a subprocess, streams its progress to stderr,
and parses its single ``{"ok":true,...}`` stdout line. On success this
script prints exactly one JSON object to stdout.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FLOW_CLI = HERE / "google_flow_cli.py"
DEFAULT_FLOW_URL = (
    "https://labs.google/fx/ko/tools/flow/project/"
    "01bad1c6-8d7a-4567-9deb-47ff1b6cd3c1"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--script-json", default="script.json", help="script JSON with flow_prompt")
    p.add_argument("--storyboard-dir", default="storyboard", help="dir of scene_*.png frames")
    p.add_argument("--out", default="raw_flow.mp4", help="output MP4 path")
    p.add_argument("--flow-project-url", default=DEFAULT_FLOW_URL, help="Flow project URL")
    p.add_argument("--session", default="flow", help="Playwright agent session name")
    p.add_argument("--duration", type=int, default=8, help="clip duration in seconds")
    p.add_argument("--aspect-ratio", default="16:9", help="video aspect ratio")
    p.add_argument("--timeout", type=int, default=900, help="seconds to wait for the render")
    p.add_argument("--poll-interval", type=int, default=15, help="seconds between status polls")
    p.add_argument("--max-images", type=int, default=3, help="max storyboard frames to seed")
    p.add_argument("--flow-cli-path", default=str(DEFAULT_FLOW_CLI), help="vendored google_flow_cli.py")
    fresh = p.add_mutually_exclusive_group()
    fresh.add_argument("--fresh", dest="fresh", action="store_true", help="reload Flow project first")
    fresh.add_argument("--no-fresh", dest="fresh", action="store_false", help="skip the reload")
    p.set_defaults(fresh=True)
    p.add_argument("--no-attach", action="store_true", help="reuse an already-attached session")
    return p.parse_args()


def read_flow_prompt(script_json: Path) -> str:
    """Load the non-empty ``flow_prompt`` string from the script JSON."""
    if not script_json.exists():
        raise SystemExit(f"script JSON not found: {script_json}")
    try:
        data = json.loads(script_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"failed to read script JSON {script_json}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"script JSON must be an object: {script_json}")
    prompt = data.get("flow_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SystemExit(f"script JSON missing a non-empty 'flow_prompt': {script_json}")
    return prompt.strip()


def collect_storyboard_images(storyboard_dir: Path, max_images: int) -> list[Path]:
    """Return up to ``max_images`` sorted scene_*.png frames; empty if none."""
    if max_images < 0:
        raise SystemExit(f"--max-images must be >= 0, got {max_images}")
    if not storyboard_dir.exists():
        return []
    frames = sorted(storyboard_dir.glob("scene_*.png"))
    return frames[:max_images]


def build_command(args: argparse.Namespace, prompt: str, images: list[Path], out: Path) -> list[str]:
    """Assemble the google_flow_cli.py subprocess argv."""
    flow_cli = Path(args.flow_cli_path).resolve()
    if not flow_cli.exists():
        raise SystemExit(f"flow CLI not found: {flow_cli}")
    cmd = [
        sys.executable,
        str(flow_cli),
        "--prompt", prompt,
        "--out", str(out),
        "--app-url", args.flow_project_url,
        "--session", args.session,
        "--attach", "cdp",
        "--duration", str(args.duration),
        "--aspect-ratio", args.aspect_ratio,
        "--timeout", str(args.timeout),
        "--poll-interval", str(args.poll_interval),
    ]
    if args.fresh:
        cmd.append("--fresh")
    if args.no_attach:
        cmd.append("--no-attach")
    for image in images:
        cmd.extend(["--image", str(image.resolve())])
    return cmd


def run_flow_cli(cmd: list[str]) -> dict:
    """Run the flow CLI, inherit its stderr, and parse its final stdout JSON line."""
    sys.stderr.write(f"[generate_video] running flow CLI: {' '.join(cmd)}\n")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=None, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"flow CLI exited {proc.returncode}; see stderr above")
    return parse_flow_result((proc.stdout or "").strip())


def parse_flow_result(stdout: str) -> dict:
    """Pick the last JSON object line from the flow CLI stdout."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            return result
    raise SystemExit(f"flow CLI produced no JSON result line; stdout={stdout!r}")


def verify_output(out: Path, result: dict) -> int:
    """Confirm the rendered MP4 exists and is non-empty; return its size."""
    if not result.get("ok"):
        raise SystemExit(f"flow CLI reported failure: {result}")
    if not out.exists():
        raise SystemExit(f"flow CLI produced no output file: {out}")
    size = out.stat().st_size
    if size == 0:
        raise SystemExit(f"flow CLI wrote a zero-byte video: {out}")
    return size


def main() -> int:
    args = parse_args()
    prompt = read_flow_prompt(Path(args.script_json).resolve())
    images = collect_storyboard_images(Path(args.storyboard_dir).resolve(), args.max_images)
    sys.stderr.write(f"[generate_video] seeding {len(images)} storyboard image(s)\n")
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_command(args, prompt, images, out)
    result = run_flow_cli(cmd)
    size = verify_output(out, result)
    print(json.dumps({"ok": True, "out": str(out), "bytes": size}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
