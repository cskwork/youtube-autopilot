#!/usr/bin/env python3
"""Turn ONE still image into a normalized Ken-Burns motion clip.

Domain-agnostic. Built for "product-ad mode": when a video advertises a real,
existing product, its real UI screenshots must appear FAITHFULLY (never sent
through a generative video model that would re-render and garble the text). This
renders a still as a fixed-size, fixed-fps silent clip with a gentle pan over a
blurred cover background, so the real pixels stay crisp and every clip in the
timeline shares one geometry for a clean concat.

Output has NO audio (narration is muxed later) and a constant WxH so it concats
cleanly with Flow B-roll clips normalized to the same geometry.

Contract: prints exactly one JSON line on stdout; logs go to stderr.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path


def log(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def build_filter(w: int, h: int, dur: float, fps: int, reverse: bool,
                 src_aspect: float | None = None) -> str:
    """Blurred cover background + contained sharp foreground + subtle diagonal pan.

    The composed frame is built 8% larger than the canvas, then a constant WxH
    crop window travels linearly across that headroom over the clip duration,
    giving a calm Ken-Burns drift without ever cropping into the real UI.

    ``src_aspect`` (source w/h) picks the fit axis: a source wider than the
    canvas fits by WIDTH (height-fit would blow it past the frame), otherwise
    by height. Unknown aspect keeps the historical height fit.
    """
    bw, bh = math.ceil(w * 1.08), math.ceil(h * 1.08)
    # t in [0,dur]; fraction f in [0,1]; reverse flips the travel direction.
    f = f"(t/{dur})" if not reverse else f"(1-(t/{dur}))"
    x_expr = f"(in_w-{w})*{f}"
    y_expr = f"(in_h-{h})*{f}"
    # Foreground fits inside 94% of the canvas so side/letterbox bars are
    # filled by the blurred bg and no real UI is clipped.
    if src_aspect is not None and src_aspect > w / h:
        fg_scale = f"scale={int(w*0.94)}:-2"
    else:
        fg_scale = f"scale=-2:{int(h*0.94)}"
    return (
        f"[0:v]scale={bw}:{bh}:force_original_aspect_ratio=increase,"
        f"crop={bw}:{bh},boxblur=26:3,eq=brightness=-0.18:saturation=1.08[bg];"
        f"[0:v]{fg_scale}[fg];"
        f"[bg][fg]overlay=({bw}-w)/2:({bh}-h)/2[base];"
        f"[base]crop={w}:{h}:x='{x_expr}':y='{y_expr}',"
        f"fps={fps},format=yuv420p[v]"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", required=True, help="source still (png/jpg)")
    p.add_argument("--out", required=True, help="output MP4 path")
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    p.add_argument("--duration", type=float, default=6.0, help="clip seconds")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--reverse", action="store_true", help="flip pan direction (for variety)")
    p.add_argument("--crf", default="18")
    args = p.parse_args()

    img = Path(args.image).expanduser().resolve()
    if not img.is_file():
        raise SystemExit(f"image not found: {img}")
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    src_aspect = None
    try:
        from PIL import Image  # repo requirement (pillow); aspect drives the fit axis
        with Image.open(img) as im:
            src_aspect = im.width / im.height
    except Exception:  # noqa: BLE001 - fit falls back to the historical height fit
        log(f"could not read image size for {img}; using height fit")
    vf = build_filter(args.width, args.height, args.duration, args.fps, args.reverse,
                      src_aspect=src_aspect)
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-loop", "1", "-t", f"{args.duration}", "-i", str(img),
        "-filter_complex", vf, "-map", "[v]",
        "-c:v", "libx264", "-crf", str(args.crf), "-preset", "medium",
        "-pix_fmt", "yuv420p", "-r", str(args.fps), "-movflags", "+faststart",
        str(out),
    ]
    log(f"+ kenburns {img.name} -> {out.name} ({args.width}x{args.height}, {args.duration}s)")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg failed ({r.returncode}) for {img}")
    size = out.stat().st_size
    if size == 0:
        raise SystemExit(f"wrote zero-byte clip: {out}")
    print(json.dumps({"ok": True, "out": str(out), "bytes": size,
                      "width": args.width, "height": args.height,
                      "duration": args.duration}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
