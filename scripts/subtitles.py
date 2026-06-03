#!/usr/bin/env python3
"""Korean sentence segmentation, per-sentence TTS timing, and caption files.

The timing model is drift-free: each sentence is synthesized to its own WAV,
each duration is probed, start/end offsets accumulate, and those same WAVs are
concatenated into the full narration WAV that gets muxed. Captions are emitted
for KEY sentences only (selective, "부분부분"), so timing is frame-accurate.
"""

from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Korean-aware sentence terminators plus newlines. We keep the terminator with
# the sentence by splitting AFTER it.
_TERMINATORS = ".!?…。"
_SPLIT_RE = re.compile(rf"(?<=[{_TERMINATORS}])\s+|\n+")
_WS_RE = re.compile(r"\s+")

DEFAULT_SUPERTTS = "npm exec --yes --package github:cskwork/supertonic-tts -- supertts"


@dataclass(frozen=True)
class Segment:
    """One synthesized sentence with its WAV and timeline position."""

    text: str
    wav: str
    duration: float
    start: float
    end: float


# --- segmentation ------------------------------------------------------------

def split_sentences(text: str) -> list[str]:
    """Split Korean text into sentences on . ! ? … 。 and newlines; drop empties."""
    pieces = _SPLIT_RE.split(text)
    return [p.strip() for p in pieces if p and p.strip()]


def _normalize_ws(text: str) -> str:
    """Collapse whitespace runs so verbatim matching tolerates spacing drift."""
    return _WS_RE.sub(" ", text).strip()


# --- timing ------------------------------------------------------------------

def assemble_segments(sentences: list[str], wavs: list[str], durations: list[float]) -> list[Segment]:
    """Build Segments from sentences + their WAVs + measured durations.

    Pure: accumulates start/end offsets so captions line up with the concat WAV.
    """
    if not (len(sentences) == len(wavs) == len(durations)):
        raise ValueError("sentences, wavs, and durations must be the same length")
    segments: list[Segment] = []
    cursor = 0.0
    for text, wav, dur in zip(sentences, wavs, durations):
        segments.append(Segment(text=text, wav=wav, duration=dur, start=cursor, end=cursor + dur))
        cursor += dur
    return segments


# --- key-sentence selection --------------------------------------------------

def select_key_indices(sentences: list[str], key_sentences: list[str] | None, *, max_count: int) -> list[int]:
    """Return indices of sentences to caption: verbatim key matches, else heuristic."""
    if key_sentences:
        matched = _match_verbatim(sentences, key_sentences)
        if matched:
            return matched[:max_count]
    return _heuristic_indices(len(sentences), max_count)


def _match_verbatim(sentences: list[str], key_sentences: list[str]) -> list[int]:
    """Match each key sentence to a sentence index (whitespace-normalized)."""
    norm = [_normalize_ws(s) for s in sentences]
    indices: list[int] = []
    for key in key_sentences:
        target = _normalize_ws(key)
        for i, candidate in enumerate(norm):
            if candidate == target and i not in indices:
                indices.append(i)
                break
    return sorted(indices)


def _heuristic_indices(count: int, max_count: int) -> list[int]:
    """Sparse fallback: first sentence + roughly every 3rd, capped at max_count."""
    if count == 0:
        return []
    indices = [0] + list(range(3, count, 3))
    return sorted(set(indices))[:max_count]


# --- caption files -----------------------------------------------------------

def _srt_ts(seconds: float) -> str:
    """Format seconds as an SRT timestamp HH:MM:SS,mmm."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(segments: list[Segment], key_idx: list[int]) -> str:
    """Render an SRT caption file for the key indices only, sequentially numbered."""
    blocks: list[str] = []
    for number, idx in enumerate(key_idx, start=1):
        seg = segments[idx]
        blocks.append(
            f"{number}\n{_srt_ts(seg.start)} --> {_srt_ts(seg.end)}\n{seg.text}\n"
        )
    return "\n".join(blocks)


def _ass_ts(seconds: float) -> str:
    """Format seconds as an ASS timestamp H:MM:SS.cc (centiseconds)."""
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_header(width: int, height: int) -> str:
    """Build an ASS header sized to the ACTUAL video resolution, and tuned
    DIFFERENTLY for Shorts (9:16 vertical) vs a standard (16:9 landscape) video.

    libass scales the whole script by PlayResX/Y -> frame size. A FIXED
    1280x720 header on a 1080x1920 frame scales the Y axis ~2.67x, ballooning
    the font and pushing every un-wrapped line off both edges. So PlayRes always
    matches the real frame (1:1 scaling) and WrapStyle 0 wraps long Korean lines
    within the side margins. Then the two FORMATS diverge:

    - Shorts / vertical (height > width): viewed on a phone and the bottom ~15%
      is covered by the Shorts UI (like/share/caption/handle). Use a larger
      font (relative to width) and a tall bottom margin so captions sit ABOVE
      that UI.
    - Standard / landscape: the proven 16:9 look (font ~ width*0.034, modest
      bottom margin) — 1280x720 reproduces the original 44px / MarginV 60.
    """
    portrait = height > width
    if portrait:                               # Shorts (9:16)
        font = max(28, round(width * 0.050))
        margin_lr = round(width * 0.06)
        margin_v = round(height * 0.13)        # clear the Shorts bottom UI
    else:                                      # standard video (16:9)
        font = max(20, round(width * 0.034))
        margin_lr = round(width * 0.0625)
        margin_v = round(height * 0.085)
    outline = max(2, round(font * 0.10))
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        # White text, semi-transparent box (BorderStyle 3), bottom-centered (Alignment 2).
        f"Style: Key,Arial,{font},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,3,{outline},0,2,{margin_lr},{margin_lr},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _ass_escape(text: str) -> str:
    """Escape ASS dialogue special characters."""
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_ass(segments: list[Segment], key_idx: list[int],
              width: int = 1280, height: int = 720) -> str:
    """Render a styled ASS subtitle file for the key indices only.

    Pass the real video width/height so the captions are sized to the frame
    (9:16 Shorts or 16:9). Defaults keep the historical 16:9 behavior.
    """
    lines = [_ass_header(width, height)]
    for idx in key_idx:
        seg = segments[idx]
        lines.append(
            f"Dialogue: 0,{_ass_ts(seg.start)},{_ass_ts(seg.end)},Key,,0,0,0,,"
            f"{_ass_escape(seg.text)}\n"
        )
    return "".join(lines)


def burn_vf(ass_path: str) -> str:
    """Return the ffmpeg -vf value that burns the given ASS file in."""
    escaped = str(ass_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return f"ass='{escaped}'"


# --- per-sentence synthesis (live; not exercised by offline unit tests) ------

def log(message: str) -> None:
    print(message, file=sys.stderr)


def resolve_supertts(override: str = "") -> list[str]:
    """Resolve the supertts invocation: explicit override > PATH > npm exec."""
    if override:
        return shlex.split(override)
    if shutil.which("supertts"):
        return ["supertts"]
    return shlex.split(DEFAULT_SUPERTTS)


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(proc.stdout.strip())


def _synth_one(base: list[str], text: str, voice: str, speed: str, steps: str,
               txt_path: Path, wav_path: Path) -> None:
    """Synthesize a single sentence to its own WAV via supertts."""
    txt_path.write_text(text, encoding="utf-8")
    cmd = base + [
        "-f", str(txt_path), "--lang", "ko", "--voice", voice,
        "--speed", speed, "--steps", steps, "--no-play", "--quiet",
        "-o", str(wav_path),
    ]
    log("+ " + shlex.join(cmd))
    subprocess.run(cmd, check=True)
    if not wav_path.exists() or wav_path.stat().st_size == 0:
        raise SystemExit(f"supertts produced no audio at {wav_path}")


def synthesize_segments(
    sentences: list[str], *, supertts_command: str, voice: str, speed: str,
    steps: str, work_dir: Path,
) -> list[Segment]:
    """Synthesize EACH sentence to its own WAV, probe duration, assemble timing."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    base = resolve_supertts(supertts_command)
    wavs: list[str] = []
    durations: list[float] = []
    for i, sentence in enumerate(sentences):
        wav = work_dir / f"seg_{i:03d}.wav"
        txt = work_dir / f"seg_{i:03d}.txt"
        _synth_one(base, sentence, voice, speed, steps, txt, wav)
        wavs.append(str(wav))
        durations.append(_probe_duration(wav))
    return assemble_segments(sentences, wavs, durations)


def concat_wavs(wavs: list[str], out_wav: Path) -> Path:
    """Concatenate same-format WAVs into one narration WAV via the concat demuxer."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    listing = out_wav.with_suffix(".concat.txt")
    listing.write_text(
        "".join(f"file '{Path(w).resolve()}'\n" for w in wavs), encoding="utf-8"
    )
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
           "-i", str(listing), "-c", "copy", str(out_wav)]
    log("+ " + shlex.join(cmd))
    subprocess.run(cmd, check=True)
    listing.unlink(missing_ok=True)
    if not out_wav.exists() or out_wav.stat().st_size == 0:
        raise SystemExit(f"wav concat produced no output at {out_wav}")
    return out_wav


# --- standalone CLI ----------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True, help="UTF-8 Korean narration text file")
    parser.add_argument("--out-prefix", default="captions", help="output .srt/.ass prefix")
    parser.add_argument("--max-captions", type=int, default=8, help="max captioned sentences")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    text = Path(args.text).resolve().read_text(encoding="utf-8")
    sentences = split_sentences(text)
    # Equal placeholder durations so the CLI can preview caption structure offline.
    segs = assemble_segments(sentences, [f"{i}.wav" for i in range(len(sentences))],
                             [2.0] * len(sentences))
    key_idx = select_key_indices(sentences, None, max_count=args.max_captions)
    Path(f"{args.out_prefix}.srt").write_text(build_srt(segs, key_idx), encoding="utf-8")
    Path(f"{args.out_prefix}.ass").write_text(build_ass(segs, key_idx), encoding="utf-8")
    print(f"sentences={len(sentences)} key={len(key_idx)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
