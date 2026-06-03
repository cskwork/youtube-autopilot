#!/usr/bin/env python3
"""Local fallback renderer: turn storyboard frames into a narrated slideshow.

When Google Flow video access is not available, this builds a finished MP4 from
the storyboard PNGs (scene_*.png) using a slow Ken Burns zoom per image and
crossfade transitions, timed to a narration WAV (or an explicit duration), then
muxes the audio. No Flow credits, no browser, no watermark to remove.

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
    p.add_argument("--storyboard-dir", default="storyboard", help="dir of scene_*.png frames")
    p.add_argument("--audio", default="", help="narration WAV; its duration drives the video length")
    p.add_argument("--duration", type=float, default=0.0, help="total seconds when --audio is absent")
    p.add_argument("--out", default="slideshow.mp4", help="output MP4 path")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--overlap", type=float, default=0.7, help="crossfade seconds between frames")
    p.add_argument("--zoom", type=float, default=0.0009, help="per-frame zoom increment (Ken Burns)")
    p.add_argument("--zoom-max", type=float, default=1.16, help="max zoom factor")
    return p.parse_args()


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def frames(storyboard_dir: Path) -> list[Path]:
    images = sorted(storyboard_dir.glob("scene_*.png"))
    if not images:
        raise SystemExit(f"no scene_*.png frames in {storyboard_dir}")
    return images


def segment_seconds(total: float, count: int, overlap: float) -> float:
    """Per-image length so the xfade chain lands on the target total duration."""
    if count == 1:
        return total
    return (total + (count - 1) * overlap) / count


def zoompan_clip(index: int, seg: float, args: argparse.Namespace) -> str:
    """One Ken Burns segment from a looped still image."""
    w, h, fps = args.width, args.height, args.fps
    nframes = max(1, int(round(seg * fps)))
    # Oversample so the zoom stays sharp, centre the pan, then trim to the segment.
    return (
        f"[{index}:v]scale={w * 4}:{h * 4}:force_original_aspect_ratio=increase,"
        f"crop={w * 4}:{h * 4},"
        f"zoompan=z='min(zoom+{args.zoom},{args.zoom_max})':d={nframes}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},"
        f"trim=duration={seg:.3f},setsar=1,format=yuv420p[v{index}]"
    )


def xfade_chain(count: int, seg: float, overlap: float) -> tuple[str, str]:
    """Crossfade the per-image segments into one stream; return (graph, last_label)."""
    if count == 1:
        return "", "v0"
    parts: list[str] = []
    prev = "v0"
    for i in range(1, count):
        out = f"x{i}"
        offset = i * seg - i * overlap
        parts.append(
            f"[{prev}][v{i}]xfade=transition=fade:duration={overlap:.3f}:offset={offset:.3f}[{out}]"
        )
        prev = out
    return ";".join(parts), prev


def build_filter(count: int, seg: float, args: argparse.Namespace) -> tuple[str, str]:
    clips = ";".join(zoompan_clip(i, seg, args) for i in range(count))
    chain, last = xfade_chain(count, seg, args.overlap)
    graph = clips if not chain else f"{clips};{chain}"
    return graph, last


def build_command(images: list[Path], seg: float, total: float, args: argparse.Namespace) -> list[str]:
    cmd: list[str] = ["ffmpeg", "-v", "error", "-y"]
    for img in images:
        cmd += ["-loop", "1", "-framerate", str(args.fps), "-t", f"{seg:.3f}", "-i", str(img)]
    audio = Path(args.audio).resolve() if args.audio else None
    if audio:
        cmd += ["-i", str(audio)]
    graph, last = build_filter(len(images), seg, args)
    cmd += ["-filter_complex", graph, "-map", f"[{last}]"]
    if audio:
        cmd += ["-map", f"{len(images)}:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [
        "-t", f"{total:.3f}", "-c:v", "libx264", "-crf", "19", "-preset", "medium",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(Path(args.out).resolve()),
    ]
    return cmd


def main() -> int:
    args = parse_args()
    images = frames(Path(args.storyboard_dir).resolve())
    if args.audio:
        total = probe_duration(Path(args.audio).resolve())
    elif args.duration > 0:
        total = args.duration
    else:
        raise SystemExit("provide --audio or --duration")
    seg = segment_seconds(total, len(images), args.overlap)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_command(images, seg, total, args)
    log("+ " + " ".join(cmd[:14]) + f" ... ({len(images)} frames, seg={seg:.2f}s, total={total:.2f}s)")
    if subprocess.run(cmd).returncode != 0:
        raise SystemExit("ffmpeg slideshow render failed")
    if not out.exists() or out.stat().st_size == 0:
        raise SystemExit(f"slideshow produced no output: {out}")
    print(json.dumps({"ok": True, "out": str(out), "frames": len(images),
                      "duration": round(total, 2)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
