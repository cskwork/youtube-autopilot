#!/usr/bin/env python3
"""Stage 5 - remove the bottom-right (Gemini/Flow) watermark via ffmpeg delogo."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

CORNERS = ("bottom-right", "bottom-left", "top-right", "top-left")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="inp", required=True, help="input video path")
    parser.add_argument("--out", default="delogo.mp4", help="output video path")
    parser.add_argument("--corner", default="bottom-right", choices=CORNERS)
    parser.add_argument("--box", default="", help="explicit x:y:w:h overriding corner+fractions")
    parser.add_argument("--margin", type=int, default=12, help="pixels from the frame edge")
    parser.add_argument("--w-frac", type=float, default=0.20, help="box width as fraction of frame width")
    parser.add_argument("--h-frac", type=float, default=0.10, help="box height as fraction of frame height")
    parser.add_argument("--show-region", action="store_true", help="also write <out>.region.png with the box drawn")
    parser.add_argument("--reencode-crf", type=int, default=18, help="libx264 CRF for the re-encode")
    return parser.parse_args()


def compute_box(
    width: int,
    height: int,
    corner: str,
    margin: int,
    w_frac: float,
    h_frac: float,
) -> tuple[int, int, int, int]:
    """Return a delogo box (x, y, w, h) clamped fully inside the frame.

    delogo requires x>=1, y>=1, x+w<=width-1, y+h<=height-1, so the usable
    interior is [1, width-2] x [1, height-2]. The box is placed in the
    requested corner inset by ``margin``, then clamped to that interior.
    """
    if corner not in CORNERS:
        raise SystemExit(f"unknown corner: {corner}")
    avail_w = max(0, width - 2)
    avail_h = max(0, height - 2)
    box_w = _clamp(round(width * w_frac), 1, avail_w)
    box_h = _clamp(round(height * h_frac), 1, avail_h)
    x = _corner_x(corner, width, box_w, margin)
    y = _corner_y(corner, height, box_h, margin)
    x = _clamp(x, 1, width - 1 - box_w)
    y = _clamp(y, 1, height - 1 - box_h)
    return x, y, box_w, box_h


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _corner_x(corner: str, width: int, box_w: int, margin: int) -> int:
    if corner.endswith("right"):
        return width - 1 - margin - box_w
    return 1 + margin


def _corner_y(corner: str, height: int, box_h: int, margin: int) -> int:
    if corner.startswith("bottom"):
        return height - 1 - margin - box_h
    return 1 + margin


def parse_box(spec: str, width: int, height: int) -> tuple[int, int, int, int]:
    """Parse an explicit ``x:y:w:h`` spec and validate delogo constraints."""
    parts = spec.split(":")
    if len(parts) != 4:
        raise SystemExit(f"--box must be x:y:w:h, got: {spec!r}")
    try:
        x, y, w, h = (int(p) for p in parts)
    except ValueError as exc:
        raise SystemExit(f"--box values must be integers: {spec!r}") from exc
    if w < 1 or h < 1:
        raise SystemExit(f"--box w and h must be >= 1: {spec!r}")
    if x < 1 or y < 1 or x + w > width - 1 or y + h > height - 1:
        raise SystemExit(f"--box {spec!r} falls outside frame {width}x{height} delogo bounds")
    return x, y, w, h


def probe_resolution(path: Path) -> tuple[int, int]:
    """Return the (width, height) of the first video stream via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    line = proc.stdout.strip().splitlines()[0]
    width_str, height_str = line.split("x")
    return int(width_str), int(height_str)


def run(cmd: list[str]) -> None:
    print("+", shlex.join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)


def apply_delogo(inp: Path, out: Path, box: tuple[int, int, int, int], crf: int) -> None:
    x, y, w, h = box
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(inp),
        "-vf",
        f"delogo=x={x}:y={y}:w={w}:h={h}",
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "copy",
        str(out),
    ]
    run(cmd)


def render_region(inp: Path, region_out: Path, box: tuple[int, int, int, int]) -> None:
    """Write one frame with the delogo box outlined for visual verification."""
    x, y, w, h = box
    draw = f"drawbox=x={x}:y={y}:w={w}:h={h}:color=red@1.0:thickness=4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(inp), "-vf", draw, "-frames:v", "1", str(region_out)]
    run(cmd)


def main() -> int:
    args = parse_args()
    inp = Path(args.inp).resolve()
    if not inp.exists():
        raise SystemExit(f"input not found: {inp}")
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = probe_resolution(inp)
    if args.box:
        box = parse_box(args.box, width, height)
    else:
        box = compute_box(width, height, args.corner, args.margin, args.w_frac, args.h_frac)
    apply_delogo(inp, out, box, args.reencode_crf)
    result: dict[str, object] = {
        "ok": True,
        "out": str(out),
        "box": list(box),
        "resolution": [width, height],
    }
    if args.show_region:
        region_out = out.with_suffix(out.suffix + ".region.png")
        render_region(inp, region_out, box)
        result["region"] = str(region_out)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
