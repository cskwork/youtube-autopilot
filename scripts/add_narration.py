#!/usr/bin/env python3
"""Stage 6 conductor - Korean narration + low BGM + selective key captions.

Synthesizes Korean narration with Supertonic, lays a low-volume royalty-free
background-music bed under it (with optional sidechain ducking), burns ONLY the
key sentences as captions at frame-accurate times, then muxes everything into
one MP4. Subtitles and BGM are ON by default; `--no-subtitles` / `--no-bgm`
restore the prior single-shot, music-free behavior.

Emits exactly one JSON line on stdout; all logs go to stderr.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load_sibling(name: str):
    """Import a sibling scripts/ module by path (cwd-independent)."""
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


audio_mix = _load_sibling("audio_mix")
subtitles = _load_sibling("subtitles")
bgm_library = _load_sibling("bgm_library")

VOICE_NAMES = {
    "F1": "Mina", "F2": "Sora", "F3": "Yuna",
    "M1": "Aiden", "M2": "Hiro", "M3": "Leo",
}
DEFAULT_SUPERTTS = subtitles.DEFAULT_SUPERTTS
DEFAULT_BGM_CACHE = _HERE.parent / "references" / "bgm_cache"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    _add_io_args(parser)
    _add_tts_args(parser)
    _add_bgm_args(parser)
    _add_caption_args(parser)
    return parser.parse_args()


def _add_io_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--in", dest="input", required=True, help="input MP4 to inspect")
    parser.add_argument("--out", default="narrated.mp4", help="output MP4 path")
    parser.add_argument("--script-json", help="JSON with narration_ko / bgm_mood / key_sentences")
    parser.add_argument("--transcript-file", help="UTF-8 Korean narration text file")
    parser.add_argument("--force-tts", action="store_true", help="synthesize even if audio exists")
    parser.add_argument("--keep-original-audio", action="store_true",
                        help="mix the existing audio track into the bed too")


def _add_tts_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--voice", default="F1", help="Supertonic voice id (default F1/Mina)")
    parser.add_argument("--speed", default="0.95", help="Supertonic speed (default 0.95)")
    parser.add_argument("--steps", default="16", help="Supertonic diffusion steps (default 16)")
    parser.add_argument("--supertts-command", default="",
                        help="override supertts invocation, e.g. 'supertts'")


def _add_bgm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bgm", help="explicit BGM track path (highest priority)")
    parser.add_argument("--bgm-mood", default="", help="BGM mood/genre keywords override")
    parser.add_argument("--bgm-volume", type=float, default=0.16, help="BGM gain (default 0.16)")
    parser.add_argument("--no-bgm", dest="bgm_on", action="store_false", help="disable BGM")
    parser.add_argument("--duck", dest="duck", action="store_true", help="sidechain ducking (default on)")
    parser.add_argument("--no-duck", dest="duck", action="store_false", help="disable sidechain ducking")
    parser.set_defaults(bgm_on=True, duck=True)


def _add_caption_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--subtitles", dest="subtitles_on", action="store_true",
                        help="burn selective key captions (default on)")
    parser.add_argument("--no-subtitles", dest="subtitles_on", action="store_false",
                        help="disable captions; single-shot whole-text TTS")
    parser.add_argument("--max-captions", type=int, default=8, help="max captioned sentences")
    parser.add_argument("--max-caption-chars", type=int, default=60,
                        help="reserved: max chars per caption line")
    parser.set_defaults(subtitles_on=True)


# --- shared helpers ----------------------------------------------------------

def log(message: str) -> None:
    print(message, file=sys.stderr)


def run(cmd: list[str]) -> None:
    log("+ " + shlex.join(cmd))
    subprocess.run(cmd, check=True)


def _probe(path: Path, entries: str, stream: str | None = None) -> str:
    cmd = ["ffprobe", "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "default=nw=1:nk=1", str(path)]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def has_audio_stream(path: Path) -> bool:
    return bool(_probe(path, "stream=index", "a"))


def video_is_h264(path: Path) -> bool:
    return _probe(path, "stream=codec_name", "v:0") == "h264"


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


# --- script fields -----------------------------------------------------------

def read_script_fields(path: Path) -> dict[str, object]:
    """Read narration_ko + optional bgm_mood / key_sentences / youtube (tolerant)."""
    if not path.exists():
        raise SystemExit(f"missing script JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"script JSON must be an object: {path}")
    narration = data.get("narration_ko")
    if not isinstance(narration, str) or not narration.strip():
        raise SystemExit(f"missing or empty narration_ko in {path}")
    keys = data.get("key_sentences")
    youtube = data.get("youtube") if isinstance(data.get("youtube"), dict) else {}
    return {
        "narration_ko": narration.strip(),
        "bgm_mood": str(data.get("bgm_mood", "")).strip(),
        "key_sentences": keys if isinstance(keys, list) else None,
        "youtube": youtube,
    }


def resolve_narration(args: argparse.Namespace) -> dict[str, object]:
    """Resolve narration text + metadata from --script-json or --transcript-file."""
    if args.script_json:
        return read_script_fields(Path(args.script_json).resolve())
    if args.transcript_file:
        text = Path(args.transcript_file).resolve().read_text(encoding="utf-8").strip()
        if not text:
            raise SystemExit("narration text is empty")
        return {"narration_ko": text, "bgm_mood": "", "key_sentences": None, "youtube": {}}
    raise SystemExit("narration source required: pass --script-json or --transcript-file")


def resolve_mood(args: argparse.Namespace, fields: dict[str, object]) -> str:
    """Pick the BGM mood: flag > script field > derived from youtube > default."""
    if args.bgm_mood:
        return args.bgm_mood
    if fields["bgm_mood"]:
        return str(fields["bgm_mood"])
    youtube = fields.get("youtube") or {}
    tags = youtube.get("tags") if isinstance(youtube, dict) else None
    title = youtube.get("title") if isinstance(youtube, dict) else None
    derived = " ".join(t for t in (list(tags or [])[:3] + [str(title or "")]) if t).strip()
    return derived or "calm ambient"


# --- TTS paths ---------------------------------------------------------------

def synth_whole(args: argparse.Namespace, text: str, work_dir: Path) -> Path:
    """Single-shot whole-text synthesis (subtitles off / back-compat path)."""
    base = subtitles.resolve_supertts(args.supertts_command)
    txt = work_dir / "narration.txt"
    txt.write_text(text, encoding="utf-8")
    wav = work_dir / "narration.wav"
    subtitles._synth_one(base, text, args.voice, args.speed, args.steps, txt, wav)
    return wav


def synth_with_captions(args: argparse.Namespace, text: str, keys, work_dir: Path):
    """Per-sentence synthesis -> concat narration WAV + key indices + .srt/.ass."""
    sentences = subtitles.split_sentences(text)
    segments = subtitles.synthesize_segments(
        sentences, supertts_command=args.supertts_command, voice=args.voice,
        speed=args.speed, steps=args.steps, work_dir=work_dir / "segments",
    )
    narration = subtitles.concat_wavs([s.wav for s in segments], work_dir / "narration.wav")
    key_idx = subtitles.select_key_indices(sentences, keys, max_count=args.max_captions)
    return narration, segments, key_idx


def write_captions(segments, key_idx, out_dir: Path) -> dict[str, object]:
    """Persist .srt + .ass sidecars beside the output; return their paths."""
    srt = out_dir / "captions.srt"
    ass = out_dir / "captions.ass"
    srt.write_text(subtitles.build_srt(segments, key_idx), encoding="utf-8")
    ass.write_text(subtitles.build_ass(segments, key_idx), encoding="utf-8")
    return {"srt": str(srt), "ass": str(ass), "key_count": len(key_idx)}


# --- BGM ---------------------------------------------------------------------

def resolve_bgm(args: argparse.Namespace, mood: str, narration_wav: Path, work_dir: Path):
    """Resolve one royalty-free track for the mood (synth fallback guarantees one)."""
    duration = audio_mix.media_duration(narration_wav)
    return bgm_library.resolve(
        mood, explicit_path=args.bgm, cache_dir=DEFAULT_BGM_CACHE,
        duration=duration, work_dir=work_dir / "bgm",
    )


def build_audio_track(args: argparse.Namespace, narration_wav: Path, src: Path,
                      bgm, work_dir: Path) -> Path:
    """Produce the final audio track: narration alone, or mixed under a BGM bed."""
    if bgm is None:
        return narration_wav
    keep = src if (args.keep_original_audio and has_audio_stream(src)) else None
    return audio_mix.mix_audio(
        narration_wav, Path(bgm.path), work_dir / "mixed.m4a",
        keep_original_src=keep, bgm_volume=args.bgm_volume, duck=args.duck,
    )


# --- final mux ---------------------------------------------------------------

def _video_codec_args(src: Path, burn_ass: str | None) -> list[str]:
    """Burning subtitles forces a re-encode; otherwise copy H.264 if possible."""
    if burn_ass is not None:
        return ["-vf", subtitles.burn_vf(burn_ass), "-c:v", "libx264",
                "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]
    if video_is_h264(src):
        return ["-c:v", "copy"]
    return ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]


def mux_final(src: Path, audio: Path, out: Path, burn_ass: str | None) -> Path:
    """Mux video + final audio track, burning the key-caption ASS when requested."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-i", str(audio)]
    cmd += _video_codec_args(src, burn_ass)
    cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(out)]
    run(cmd)
    return out


def write_credits(out: Path, bgm) -> str | None:
    """Write CREDITS.txt beside the output when the track requires attribution."""
    if bgm is None or not bgm.attribution:
        return None
    credits = out.parent / "CREDITS.txt"
    credits.write_text(
        f"Background music: {bgm.attribution}\nLicense: {bgm.license}\n",
        encoding="utf-8",
    )
    return str(credits)


# --- conductor ---------------------------------------------------------------

def _bgm_payload(bgm) -> dict[str, object] | None:
    if bgm is None:
        return None
    return {"path": bgm.path, "source": bgm.source,
            "license": bgm.license, "attribution": bgm.attribution}


def conduct(args: argparse.Namespace, src: Path, out: Path) -> int:
    """Run TTS + BGM + captions + mux and emit the result JSON."""
    fields = resolve_narration(args)
    text = str(fields["narration_ko"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="add_narration_") as tmp:
        work = Path(tmp)
        segments, key_idx, captions, burn_ass = None, None, None, None
        if args.subtitles_on:
            narration, segments, key_idx = synth_with_captions(args, text, fields["key_sentences"], work)
            captions = write_captions(segments, key_idx, out.parent)
            burn_ass = captions["ass"]
        else:
            narration = synth_whole(args, text, work)
        bgm = None
        if args.bgm_on:
            mood = resolve_mood(args, fields)
            log(f"[bgm] mood={mood!r}")
            bgm = resolve_bgm(args, mood, narration, work)
        audio = build_audio_track(args, narration, src, bgm, work)
        out_path = mux_final(src, audio, out, burn_ass)
    credits = write_credits(out_path, bgm)
    emit({
        "ok": True, "out": str(out_path), "tts": True, "voice": args.voice,
        "voice_name": VOICE_NAMES.get(args.voice, args.voice),
        "bgm": _bgm_payload(bgm), "subtitles": captions, "credits": credits,
    })
    return 0


def copy_existing(src: Path, out: Path) -> int:
    """Audio present and TTS not forced: re-mux into the requested container."""
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c", "copy",
         "-movflags", "+faststart", str(out)])
    emit({"ok": True, "out": str(out), "tts": False, "bgm": None, "subtitles": None})
    return 0


def main() -> int:
    args = parse_args()
    src = Path(args.input).resolve()
    if not src.exists():
        raise SystemExit(f"missing input video: {src}")
    out = Path(args.out).resolve()
    if has_audio_stream(src) and not args.force_tts:
        log(f"audio stream found in {src}; copying without TTS")
        return copy_existing(src, out)
    log(f"synthesizing Korean narration ({args.voice}/{VOICE_NAMES.get(args.voice, args.voice)})")
    return conduct(args, src, out)


if __name__ == "__main__":
    raise SystemExit(main())
