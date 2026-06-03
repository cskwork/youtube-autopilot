#!/usr/bin/env python3
"""Assemble multiple Flow scene clips into one narrated, watermark-free MP4.

concat scene clips -> optional delogo -> optional fit to narration length
(setpts stretch) -> mux narration. This is the multi-scene counterpart to
build_slideshow.py (which renders from still frames when Flow is unavailable).

Prints exactly one JSON object to stdout on success; logs go to stderr.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--clips-dir", default="", help="dir to glob clips from (with --pattern)")
    p.add_argument("--pattern", default="flow_scene*.mp4", help="glob for --clips-dir")
    p.add_argument("--clip", action="append", default=[], dest="clips", help="explicit clip path; repeatable, ordered")
    p.add_argument("--narration", default="", help="narration WAV; its length drives the final duration")
    p.add_argument("--out", default="flow_final.mp4", help="output MP4 path")
    p.add_argument("--delogo-box", default="", help="x:y:w:h watermark box to wipe (e.g. 1095:600:160:100)")
    p.add_argument("--fit/--no-fit", dest="fit", default=True, action=argparse.BooleanOptionalAction,
                   help="stretch video to the narration length (default on when narration given)")
    p.add_argument("--crf", default="18")
    return p.parse_args()


def collect_clips(args: argparse.Namespace) -> list[Path]:
    if args.clips:
        clips = [Path(c).resolve() for c in args.clips]
    elif args.clips_dir:
        clips = sorted(Path(args.clips_dir).resolve().glob(args.pattern))
    else:
        raise SystemExit("provide --clip (repeatable) or --clips-dir")
    missing = [str(c) for c in clips if not c.is_file()]
    if missing:
        raise SystemExit("missing clips: " + ", ".join(missing))
    if not clips:
        raise SystemExit("no clips found")
    return clips


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def run(cmd: list[str]) -> None:
    log("+ " + " ".join(cmd[:12]) + (" ..." if len(cmd) > 12 else ""))
    if subprocess.run(cmd).returncode != 0:
        raise SystemExit("ffmpeg step failed")


def concat_clips(clips: list[Path], out: Path, crf: str) -> Path:
    """Concatenate clip video streams into one (audio dropped; narration replaces it)."""
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for clip in clips:
        cmd += ["-i", str(clip)]
    streams = "".join(f"[{i}:v]" for i in range(len(clips)))
    graph = f"{streams}concat=n={len(clips)}:v=1:a=0[v]"
    cmd += ["-filter_complex", graph, "-map", "[v]", "-an",
            "-c:v", "libx264", "-crf", crf, "-pix_fmt", "yuv420p", str(out)]
    run(cmd)
    return out


def delogo(src: Path, box: str, out: Path, crf: str) -> Path:
    """Wipe a watermark box with ffmpeg delogo (x:y:w:h)."""
    parts = box.split(":")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"--delogo-box must be x:y:w:h, got {box!r}")
    x, y, w, h = parts
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src),
         "-vf", f"delogo=x={x}:y={y}:w={w}:h={h}",
         "-c:v", "libx264", "-crf", crf, "-pix_fmt", "yuv420p", "-an", str(out)])
    return out


def finalize(video: Path, narration: Path | None, fit: bool, out: Path, crf: str) -> float:
    """Stretch video to the narration length (optional) and mux the narration."""
    if narration is None:
        run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-c", "copy",
             "-movflags", "+faststart", str(out)])
        return probe_duration(video)
    target = probe_duration(narration)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(narration)]
    if fit:
        factor = target / probe_duration(video)
        cmd += ["-filter_complex", f"[0:v]setpts={factor:.5f}*PTS,fps=30[v]", "-map", "[v]"]
    else:
        cmd += ["-map", "0:v"]
    cmd += ["-map", "1:a", "-c:v", "libx264", "-crf", crf, "-preset", "medium",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", str(out)]
    run(cmd)
    return target


def main() -> int:
    args = parse_args()
    clips = collect_clips(args)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent
    log(f"assembling {len(clips)} clip(s)")
    stitched = concat_clips(clips, work / "_concat.mp4", args.crf)
    if args.delogo_box:
        stitched = delogo(stitched, args.delogo_box, work / "_delogo.mp4", args.crf)
    narration = Path(args.narration).resolve() if args.narration else None
    if narration and not narration.is_file():
        raise SystemExit(f"narration not found: {narration}")
    duration = finalize(stitched, narration, args.fit, out, args.crf)
    print(json.dumps({"ok": True, "out": str(out), "clips": len(clips),
                      "delogo": bool(args.delogo_box), "duration": round(duration, 2)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
