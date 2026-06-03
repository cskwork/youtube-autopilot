#!/usr/bin/env python3
"""Pure ffmpeg audio-mix graph builder + runner for Stage 6 BGM.

Lays a low-gain, looped, faded background-music bed under the full narration
WAV. Optionally mixes the original video audio into the bed and ducks the bed
under the narration via a sidechain compressor. The graph builder is pure
(no ffmpeg call) so it is fully unit-testable; ``mix_audio`` probes the
narration duration and runs ffmpeg to emit one AAC/m4a track.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Sidechain ducking calibration (user-approved): the bed dips while narration
# is present, then recovers. Values are conservative for spoken-word over music.
DUCK_PARAMS = "threshold=0.03:ratio=8:attack=20:release=300"


@dataclass(frozen=True)
class MixGraph:
    """A fully-resolved ffmpeg mix description (immutable, testable)."""

    inputs: list[str]            # ordered labels: narration, bgm, [original]
    bgm_input_args: list[str]    # per-input args for the bgm input (stream loop)
    filter_complex: str          # the -filter_complex value
    map_label: str               # the labeled output pad to -map, e.g. "[mix]"


def _round(value: float) -> str:
    """Format a float for an ffmpeg filter arg, trimming trailing noise."""
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def _bed_chain(bgm_volume: float, narration_dur: float, fade: float, keep_original: bool) -> str:
    """Build the background bed: low-gain looped BGM + fades, optional original."""
    fade_out_st = max(narration_dur - fade, 0.0)
    bg = (
        f"[1:a]volume={_round(bgm_volume)},"
        f"afade=t=in:st=0:d={_round(fade)},"
        f"afade=t=out:st={fade_out_st:.1f}:d={_round(fade)}[bg]"
    )
    if not keep_original:
        return bg
    # Mix the original video audio into the bed at the same low gain.
    orig = f"[2:a]volume={_round(bgm_volume)}[orig]"
    bed = "[bg][orig]amix=inputs=2:duration=first:normalize=0[bed]"
    return ";".join([bg, orig, bed])


def build_mix_graph(
    *,
    narration_dur: float,
    bgm_volume: float = 0.16,
    duck: bool = True,
    fade: float = 1.0,
    keep_original: bool = False,
) -> MixGraph:
    """Compose the pure ffmpeg mix graph for narration + low BGM bed.

    Inputs are ordered narration(0), bgm(1), and optionally original(2). The
    bed is trimmed to the narration length (``amix ... duration=first``); the
    narration is never auto-attenuated (``normalize=0``).
    """
    inputs = ["narration", "bgm"] + (["original"] if keep_original else [])
    bed_label = "[bed]" if keep_original else "[bg]"
    parts = [_bed_chain(bgm_volume, narration_dur, fade, keep_original)]
    narration_pad = "[0:a]"
    if duck:
        # Split the narration pad explicitly: one copy keys the sidechain
        # compressor, the other feeds the final amix. Avoids relying on
        # ffmpeg's implicit input-pad auto-split (portability).
        parts.append("[0:a]asplit=2[nar0][nar1]")
        parts.append(f"{bed_label}[nar0]sidechaincompress={DUCK_PARAMS}[bgd]")
        bed_label = "[bgd]"
        narration_pad = "[nar1]"
    parts.append(f"{narration_pad}{bed_label}amix=inputs=2:duration=first:normalize=0[mix]")
    return MixGraph(
        inputs=inputs,
        bgm_input_args=["-stream_loop", "-1"],
        filter_complex=";".join(parts),
        map_label="[mix]",
    )


# --- runner ------------------------------------------------------------------

def log(message: str) -> None:
    print(message, file=sys.stderr)


def media_duration(path: Path) -> float:
    """Probe a media file's duration in seconds."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(proc.stdout.strip())


def mix_audio(
    narration_wav: Path,
    bgm_path: Path,
    out_path: Path,
    *,
    keep_original_src: Path | None = None,
    bgm_volume: float = 0.16,
    duck: bool = True,
    fade: float = 1.0,
) -> Path:
    """Probe narration duration, run ffmpeg, emit one mixed AAC/m4a track.

    Inputs are not mutated. ``keep_original_src`` (a video/audio file) mixes its
    audio into the bed when supplied.
    """
    narration_wav = Path(narration_wav)
    bgm_path = Path(bgm_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dur = media_duration(narration_wav)
    graph = build_mix_graph(
        narration_dur=dur, bgm_volume=bgm_volume, duck=duck, fade=fade,
        keep_original=keep_original_src is not None,
    )
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(narration_wav)]
    cmd += [*graph.bgm_input_args, "-i", str(bgm_path)]
    if keep_original_src is not None:
        cmd += ["-i", str(keep_original_src)]
    cmd += [
        "-filter_complex", graph.filter_complex,
        "-map", graph.map_label,
        "-c:a", "aac", "-b:a", "192k", str(out_path),
    ]
    log("+ " + shlex.join(cmd))
    subprocess.run(cmd, check=True)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise SystemExit(f"audio mix produced no output at {out_path}")
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--narration", required=True, help="narration WAV path")
    parser.add_argument("--bgm", required=True, help="background music path")
    parser.add_argument("--out", default="mixed.m4a", help="output mixed audio")
    parser.add_argument("--keep-original", help="video/audio file to mix into the bed")
    parser.add_argument("--bgm-volume", type=float, default=0.16, help="BGM gain (default 0.16)")
    parser.add_argument("--no-duck", dest="duck", action="store_false", help="disable sidechain ducking")
    parser.add_argument("--fade", type=float, default=1.0, help="fade in/out seconds (default 1.0)")
    parser.set_defaults(duck=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out = mix_audio(
        Path(args.narration).resolve(),
        Path(args.bgm).resolve(),
        Path(args.out).resolve(),
        keep_original_src=Path(args.keep_original).resolve() if args.keep_original else None,
        bgm_volume=args.bgm_volume,
        duck=args.duck,
        fade=args.fade,
    )
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
