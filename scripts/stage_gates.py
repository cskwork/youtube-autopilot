#!/usr/bin/env python3
"""Per-stage output verification gates for the autopilot pipeline.

The orchestrator trusts each stage's ``{"ok": true}`` JSON contract, but a stage
can exit 0 and still hand on a degraded artifact: a truncated MP4, a video with
no audio, a SILENT narration track (TTS produced nothing), an empty ideas file,
or a storyboard with no rendered frames. These gates re-inspect the REAL
artifact after each stage and raise ``GateError`` the moment something is missing
or invalid, so the pipeline hard-stops instead of carrying a broken artifact
forward — and never uploads one.

This is the teeth behind "each stage must pass": exit-code-0 is necessary but
not sufficient; the produced file must actually be a usable artifact.

Pure verification helpers (ffprobe/ffmpeg only); no pipeline state. Unit-tested
against ffmpeg-built good/bad fixtures.

Emits nothing on stdout; callers convert ``GateError`` into a hard stop.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

# A narration track quieter than this mean level (dBFS) is treated as
# effectively silent -> a TTS failure that produced no real speech.
DEFAULT_SILENCE_DB = -50.0
# ffmpeg volumedetect prints e.g. "mean_volume: -23.5 dB" (or "-inf dB" for
# digital silence) on stderr.
_MEAN_VOLUME_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?|-?inf)\s*dB")


class GateError(Exception):
    """Raised when a stage's real output fails verification (hard stop)."""


# Mirrors subtitles.py sentence segmentation so this module's caption checks
# (verbatim key sentences, captioned CTA) predict what the caption stage sees.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…。])\s+|\n+")
_WS_RE = re.compile(r"\s+")
# Korean speech pacing used to budget hook/total length WITHOUT running TTS
# (same constant the orchestrator uses to size the slideshow).
DEFAULT_CHARS_PER_SECOND = 5.5


# --- ffprobe / ffmpeg probes -------------------------------------------------

def _ffprobe(path: Path, entries: str, stream: str | None = None) -> str:
    """Run ffprobe for one entry set; return stdout, or "" on any error."""
    cmd = ["ffprobe", "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "default=nw=1:nk=1", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def has_video_stream(path: Path) -> bool:
    """True if the file has at least one video stream."""
    return bool(_ffprobe(path, "stream=index", "v:0"))


def has_audio_stream(path: Path) -> bool:
    """True if the file has at least one audio stream."""
    return bool(_ffprobe(path, "stream=index", "a:0"))


def probe_duration(path: Path) -> float:
    """Return container duration in seconds, or 0.0 if unknown/unreadable."""
    try:
        return float(_ffprobe(path, "format=duration"))
    except ValueError:
        return 0.0


def mean_volume_db(path: Path) -> float:
    """Return the first audio stream's mean volume (dBFS) via volumedetect.

    Returns ``-inf`` for a missing/undetectable or fully silent track, so a
    silent narration trips the silence threshold below.
    """
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
           "-map", "0:a:0?", "-af", "volumedetect", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    match = _MEAN_VOLUME_RE.search(proc.stderr or "")
    if match:
        value = match.group(1)
        return float("-inf") if "inf" in value else float(value)
    # No reading and ffmpeg errored: a decode/container failure, NOT silence.
    # Surface it as such instead of misdiagnosing it as a TTS-silent failure.
    if proc.returncode != 0:
        raise GateError(f"volumedetect failed for {path} (rc={proc.returncode}); audio may be corrupt")
    return float("-inf")


# --- media artifact gates ----------------------------------------------------

def _require_file(path: Path, label: str, *, min_bytes: int) -> None:
    """Assert the file exists and is at least ``min_bytes`` on disk."""
    if not path.exists():
        raise GateError(f"{label}: missing output file {path}")
    size = path.stat().st_size
    if size < min_bytes:
        raise GateError(f"{label}: output {path} too small ({size} < {min_bytes} bytes)")


def gate_video(path: Path, *, label: str = "video",
               min_duration: float = 1.0, min_bytes: int = 1024) -> dict:
    """Assert a real, non-trivial video: present file + video stream + duration."""
    _require_file(path, label, min_bytes=min_bytes)
    if not has_video_stream(path):
        raise GateError(f"{label}: no video stream in {path}")
    dur = probe_duration(path)
    if dur <= 0.0:
        raise GateError(
            f"{label}: could not read a valid duration for {path} ({dur:.3f}s); "
            "file may be truncated or corrupt"
        )
    if dur < min_duration:
        raise GateError(
            f"{label}: duration {dur:.3f}s below minimum {min_duration:.3f}s ({path})"
        )
    return {"duration": dur, "bytes": path.stat().st_size}


def gate_narration(path: Path, *, label: str = "narration", min_duration: float = 1.0,
                   max_silence_db: float = DEFAULT_SILENCE_DB, min_bytes: int = 1024) -> dict:
    """Assert the narrated video carries REAL, audible audio (TTS succeeded).

    Catches the silent-failure case the ``{"tts": true}`` flag cannot: an audio
    stream that exists but is empty/silent.
    """
    info = gate_video(path, label=label, min_duration=min_duration, min_bytes=min_bytes)
    if not has_audio_stream(path):
        raise GateError(f"{label}: no audio stream in {path} (TTS produced nothing)")
    mean = mean_volume_db(path)
    if mean <= max_silence_db:
        raise GateError(
            f"{label}: audio effectively silent (mean {mean} dB <= {max_silence_db} dB); "
            f"TTS likely failed for {path}"
        )
    info["mean_volume_db"] = mean
    return info


# --- JSON / asset gates ------------------------------------------------------

def _load_json(path: Path, label: str):
    """Load JSON or raise a clear GateError on missing/invalid content."""
    if not path.exists():
        raise GateError(f"{label}: missing file {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"{label}: unreadable/invalid JSON {path}: {exc}") from exc


def gate_ideas(path: Path, *, min_count: int = 1, label: str = "harvest") -> dict:
    """Assert the harvest produced at least ``min_count`` ideas."""
    data = _load_json(path, label)
    ideas = data.get("ideas", data) if isinstance(data, dict) else data
    count = len(ideas) if isinstance(ideas, list) else 0
    if count < min_count:
        raise GateError(f"{label}: need >= {min_count} ideas in {path}, got {count}")
    return {"count": count}


def gate_script(path: Path, *, label: str = "script") -> dict:
    """Assert the script has non-empty narration_ko and flow_prompt."""
    data = _load_json(path, label)
    if not isinstance(data, dict):
        raise GateError(f"{label}: script JSON must be an object: {path}")
    narration = data.get("narration_ko")
    if not isinstance(narration, str) or not narration.strip():
        raise GateError(f"{label}: missing/empty narration_ko in {path}")
    flow = data.get("flow_prompt")
    if not isinstance(flow, str) or not flow.strip():
        raise GateError(f"{label}: missing/empty flow_prompt in {path}")
    return {"narration_chars": len(narration.strip())}


def gate_storyboard(storyboard_dir: Path, *, min_scenes: int = 1,
                    min_bytes: int = 1024, label: str = "storyboard") -> dict:
    """Assert storyboard.json parses and >= ``min_scenes`` real scene_*.png frames."""
    _load_json(storyboard_dir / "storyboard.json", label)
    frames = sorted(storyboard_dir.glob("scene_*.png"))
    if len(frames) < min_scenes:
        raise GateError(
            f"{label}: need >= {min_scenes} scene_*.png in {storyboard_dir}, got {len(frames)}"
        )
    for frame in frames:
        size = frame.stat().st_size
        if size < min_bytes:
            raise GateError(f"{label}: frame {frame} too small ({size} < {min_bytes} bytes)")
    return {"frames": len(frames)}


def gate_page_facts(path: Path, *, label: str = "ingest_url") -> dict:
    """Assert ingested page facts carry the grounding a marketing script needs.

    The URL-AD workflow's script stage is grounded in these facts (it must not
    invent features) and maps them onto a hook -> USP -> CTA structure, so the
    load-bearing fields are an identity (url + title), at least one value
    proposition (the USP source), and a call-to-action (cta_text).
    """
    data = _load_json(path, label)
    if not isinstance(data, dict):
        raise GateError(f"{label}: page facts JSON must be an object: {path}")
    for key in ("url", "title", "cta_text"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise GateError(f"{label}: missing/empty {key} in {path}")
    props = data.get("value_props")
    if not isinstance(props, list) or not props:
        raise GateError(f"{label}: need >= 1 value_props in {path}")
    return {"value_props": len(props), "url": data["url"].strip()}


def _split_sentences(text: str) -> list[str]:
    return [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p and p.strip()]


def _norm_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def gate_ad_quality(path: Path, *, chars_per_second: float = DEFAULT_CHARS_PER_SECOND,
                    hook_max_s: float = 3.5, min_total_s: float = 12.0,
                    max_total_s: float = 60.0, label: str = "ad_quality") -> dict:
    """Assert the ad script lands the short-form conversion structure.

    Deterministic proxies for the evidence-backed rules in
    `references/workflows/url-ad.md`: the opening sentence must fit the ~3s
    hook window, the whole narration must fit the Shorts budget, every key
    sentence must match a narration sentence verbatim (else its caption slot
    never fires), and the closing CTA sentence must be captioned. Speech time
    is estimated from character count; no TTS runs here.
    """
    data = _load_json(path, label)
    if not isinstance(data, dict):
        raise GateError(f"{label}: script JSON must be an object: {path}")
    sentences = _split_sentences(str(data.get("narration_ko") or ""))
    if not sentences:
        raise GateError(f"{label}: missing/empty narration_ko in {path}")
    est_hook = len(sentences[0]) / chars_per_second
    if est_hook > hook_max_s:
        raise GateError(
            f"{label}: opening sentence is ~{est_hook:.1f}s of speech, beyond the "
            f"{hook_max_s:.1f}s hook window; front-load the value proposition"
        )
    est_total = sum(len(s) for s in sentences) / chars_per_second
    if not (min_total_s <= est_total <= max_total_s):
        raise GateError(
            f"{label}: estimated narration duration {est_total:.1f}s outside the "
            f"[{min_total_s:.0f}s, {max_total_s:.0f}s] short-form budget"
        )
    keys = data.get("key_sentences")
    if not isinstance(keys, list) or not keys:
        raise GateError(f"{label}: need >= 1 key_sentences (captioned hook/CTA) in {path}")
    # Containment matching mirrors subtitles._match_verbatim: a key trimmed of
    # lead-in words still captions its containing sentence.
    norm_sentences = [_norm_ws(s) for s in sentences]
    norm_keys = [_norm_ws(str(k)) for k in keys]
    for key, norm_key in zip(keys, norm_keys):
        if not norm_key or not any(norm_key in s for s in norm_sentences):
            raise GateError(f"{label}: key sentence not verbatim in narration_ko: {key!r}")
    if not any(norm_key in norm_sentences[-1] for norm_key in norm_keys):
        raise GateError(
            f"{label}: closing CTA sentence must be in key_sentences so it is "
            f"captioned on screen: {sentences[-1]!r}"
        )
    return {"sentences": len(sentences), "key_sentences": len(keys),
            "est_hook_s": round(est_hook, 2), "est_total_s": round(est_total, 2)}
