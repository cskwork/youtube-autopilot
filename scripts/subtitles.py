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


def _caption_metrics(width: int, height: int) -> dict:
    """Per-format caption geometry: Shorts/9:16 (phone-legible font, high bottom
    margin to clear the Shorts UI) vs standard/16:9 (the proven smaller look)."""
    portrait = height > width
    if portrait:                               # Shorts (9:16)
        font = max(28, round(width * 0.050))
        margin_lr = round(width * 0.06)
        margin_v = round(height * 0.13)        # clear the Shorts bottom UI
    else:                                      # standard video (16:9)
        font = max(20, round(width * 0.034))
        margin_lr = round(width * 0.0625)
        margin_v = round(height * 0.085)
    return {"portrait": portrait, "font": font, "outline": max(2, round(font * 0.10)),
            "margin_lr": margin_lr, "margin_v": margin_v}


def _ass_header(width: int, height: int) -> str:
    """Build an ASS header sized to the ACTUAL video resolution, and tuned
    DIFFERENTLY for Shorts (9:16 vertical) vs a standard (16:9 landscape) video.

    libass scales the whole script by PlayResX/Y -> frame size. A FIXED
    1280x720 header on a 1080x1920 frame scales the Y axis ~2.67x, ballooning
    the font and pushing every un-wrapped line off both edges. So PlayRes always
    matches the real frame (1:1 scaling) and WrapStyle 0 wraps long Korean lines
    within the side margins; per-format sizing comes from `_caption_metrics`.
    """
    m = _caption_metrics(width, height)
    font, outline = m["font"], m["outline"]
    margin_lr, margin_v = m["margin_lr"], m["margin_v"]
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


# Korean variety/TV-show caption presets: (alignment, accent RGB). Cycled per
# caption so color + position keep changing; most sit at the bottom (\an2) and
# one pops to the top (\an8) for rhythm. Emphasis words get the accent colour +
# a bigger, bolder, popped scale; the rest stay white.
_CAPTION_PRESETS = [
    (2, (255, 222, 0)),    # bottom, yellow
    (8, (0, 224, 255)),    # top, cyan
    (2, (255, 90, 160)),   # bottom, pink
    (2, (124, 252, 120)),  # bottom, green
]


def _ass_color(rgb: tuple[int, int, int]) -> str:
    """RGB -> ASS &HBBGGRR& colour literal."""
    r, g, b = rgb
    return f"&H{b:02X}{g:02X}{r:02X}&"


def _norm_token(tok: str) -> str:
    """Token stripped of punctuation, for emphasis matching."""
    return "".join(ch for ch in tok if ch.isalnum())


def _emphasis_indices(tokens: list[str], emphasis: list[str] | None,
                      max_emph: int = 2) -> set[int]:
    """Which token positions to emphasize: any token whose alnum core contains a
    given emphasis term; else fall back to the single longest token so EVERY
    caption still gets one pop. Capped to the ``max_emph`` longest matches so a
    caption never turns into a wall of colour."""
    idxs: set[int] = set()
    if emphasis:
        for i, tok in enumerate(tokens):
            core = _norm_token(tok)
            if core and any(term and term in core for term in emphasis):
                idxs.add(i)
    if not idxs and tokens:
        longest = max(range(len(tokens)), key=lambda i: len(_norm_token(tokens[i])))
        if _norm_token(tokens[longest]):
            idxs.add(longest)
    if len(idxs) > max_emph:
        idxs = set(sorted(idxs, key=lambda i: len(_norm_token(tokens[i])),
                          reverse=True)[:max_emph])
    return idxs


def _style_caption(text: str, preset: tuple[int, tuple[int, int, int]],
                   base_font: int, emphasis: list[str] | None) -> str:
    """Render one caption as variety-style ASS: line-level alignment + fade,
    accent-coloured popped emphasis words, plain white for the rest."""
    align, accent = preset
    accent_c = _ass_color(accent)
    emph_fs = round(base_font * 1.34)
    tokens = text.split(" ")
    emph = _emphasis_indices(tokens, emphasis)
    parts: list[str] = []
    for i, tok in enumerate(tokens):
        esc = _ass_escape(tok)
        if i in emph:
            parts.append(
                f"{{\\c{accent_c}\\b1\\fs{emph_fs}\\fscx118\\fscy118"
                f"\\t(0,140,\\fscx100\\fscy100)}}{esc}"
                f"{{\\c&H00FFFFFF&\\b0\\fs{base_font}}}"  # reset color/bold/size, keep alignment
            )
        else:
            parts.append(esc)
    return f"{{\\an{align}\\fad(120,60)}}" + " ".join(parts)


def build_ass(segments: list[Segment], key_idx: list[int],
              width: int = 1280, height: int = 720,
              emphasis: list[str] | None = None) -> str:
    """Render a styled, Korean-variety-show ASS for the key indices only.

    Pass the real video width/height so captions size to the frame (9:16 Shorts
    or 16:9). ``emphasis`` is an optional list of key terms to highlight; tokens
    containing one are accented/enlarged, else each caption pops its longest
    token. Captions cycle through `_CAPTION_PRESETS` so colour and position keep
    changing. Defaults keep the historical 16:9 geometry.
    """
    base_font = _caption_metrics(width, height)["font"]
    lines = [_ass_header(width, height)]
    for n, idx in enumerate(key_idx):
        seg = segments[idx]
        preset = _CAPTION_PRESETS[n % len(_CAPTION_PRESETS)]
        styled = _style_caption(seg.text, preset, base_font, emphasis)
        lines.append(
            f"Dialogue: 0,{_ass_ts(seg.start)},{_ass_ts(seg.end)},Key,,0,0,0,,{styled}\n"
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
