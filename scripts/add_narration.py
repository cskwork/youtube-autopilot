#!/usr/bin/env python3
"""Stage 6 - ensure the video has Korean narration; synthesize with Supertonic if missing."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


VOICE_NAMES = {
    "F1": "Mina",
    "F2": "Sora",
    "F3": "Yuna",
    "M1": "Aiden",
    "M2": "Hiro",
    "M3": "Leo",
}
DEFAULT_SUPERTTS = "npm exec --yes --package github:cskwork/supertonic-tts -- supertts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input", required=True, help="input MP4 to inspect")
    parser.add_argument("--out", default="narrated.mp4", help="output MP4 path")
    parser.add_argument("--script-json", help="JSON file containing a narration_ko field")
    parser.add_argument("--transcript-file", help="UTF-8 Korean narration text file")
    parser.add_argument("--voice", default="F1", help="Supertonic voice id (default F1/Mina)")
    parser.add_argument("--speed", default="0.95", help="Supertonic speed (default 0.95)")
    parser.add_argument("--steps", default="16", help="Supertonic diffusion steps (default 16)")
    parser.add_argument("--force-tts", action="store_true", help="synthesize even if audio exists")
    parser.add_argument(
        "--keep-original-audio",
        action="store_true",
        help="mix synthesized narration with the existing audio track",
    )
    parser.add_argument(
        "--supertts-command",
        default="",
        help="override supertts invocation, e.g. 'supertts' or 'npx ...'",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(message, file=sys.stderr)


def run(cmd: list[str]) -> None:
    log("+ " + shlex.join(cmd))
    subprocess.run(cmd, check=True)


def supertts_command(args: argparse.Namespace) -> list[str]:
    if args.supertts_command:
        return shlex.split(args.supertts_command)
    if shutil.which("supertts"):
        return ["supertts"]
    return shlex.split(DEFAULT_SUPERTTS)


def media_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(proc.stdout.strip())


def has_audio_stream(path: Path) -> bool:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(proc.stdout.strip())


def resolve_narration_text(args: argparse.Namespace) -> str:
    if args.script_json:
        text = read_script_json(Path(args.script_json).resolve())
    elif args.transcript_file:
        text = Path(args.transcript_file).resolve().read_text(encoding="utf-8")
    else:
        raise SystemExit("narration source required: pass --script-json or --transcript-file")
    text = text.strip()
    if not text:
        raise SystemExit("narration text is empty")
    return text


def read_script_json(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"missing script JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}") from exc
    narration = data.get("narration_ko") if isinstance(data, dict) else None
    if not isinstance(narration, str) or not narration.strip():
        raise SystemExit(f"missing or empty narration_ko in {path}")
    return narration


def write_temp_transcript(text: str, work_dir: Path) -> Path:
    handle, name = tempfile.mkstemp(suffix=".txt", prefix="narration_", dir=str(work_dir))
    os.close(handle)
    transcript = Path(name)
    transcript.write_text(text, encoding="utf-8")
    return transcript


def synthesize_voice(args: argparse.Namespace, transcript: Path, out_wav: Path) -> Path:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = supertts_command(args)
    cmd.extend([
        "-f",
        str(transcript),
        "--lang",
        "ko",
        "--voice",
        args.voice,
        "--speed",
        args.speed,
        "--steps",
        args.steps,
        "--no-play",
        "--quiet",
        "-o",
        str(out_wav),
    ])
    run(cmd)
    if not out_wav.exists() or out_wav.stat().st_size == 0:
        raise SystemExit(f"supertts produced no audio at {out_wav}")
    return out_wav


def video_is_h264(path: Path) -> bool:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip() == "h264"


def video_codec_args(path: Path) -> list[str]:
    # Copy the video stream untouched when it is already H.264; otherwise re-encode.
    if video_is_h264(path):
        return ["-c:v", "copy"]
    return ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]


def copy_with_audio(src: Path, out: Path) -> Path:
    # Audio already present and TTS not forced: re-mux into the requested container path.
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(src),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(out),
    ]
    run(cmd)
    return out


def mux_narration(src: Path, wav: Path, out: Path, keep_original: bool) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-i", str(wav)]
    cmd.extend(audio_map_args(src, keep_original))
    cmd.extend(video_codec_args(src))
    cmd.extend([
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ])
    run(cmd)
    return out


def audio_map_args(src: Path, keep_original: bool) -> list[str]:
    # Default: replace audio with the WAV narration. When keeping the original and
    # the source has an audio track, mix both into a single stereo stream.
    if keep_original and has_audio_stream(src):
        return [
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=2[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
        ]
    return ["-map", "0:v:0", "-map", "1:a:0"]


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def handle_existing_audio(src: Path, out: Path) -> int:
    out_path = copy_with_audio(src, out)
    emit({"ok": True, "out": str(out_path), "tts": False})
    return 0


def handle_synthesis(args: argparse.Namespace, src: Path, out: Path) -> int:
    text = resolve_narration_text(args)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="add_narration_") as tmp:
        transcript = write_temp_transcript(text, Path(tmp))
        wav = synthesize_voice(args, transcript, out.with_suffix(".narration.wav"))
        out_path = mux_narration(src, wav, out, args.keep_original_audio)
    emit({
        "ok": True,
        "out": str(out_path),
        "tts": True,
        "voice": args.voice,
        "voice_name": VOICE_NAMES.get(args.voice, args.voice),
        "wav": str(wav),
    })
    return 0


def main() -> int:
    args = parse_args()
    src = Path(args.input).resolve()
    if not src.exists():
        raise SystemExit(f"missing input video: {src}")
    out = Path(args.out).resolve()
    audio_present = has_audio_stream(src)
    if audio_present and not args.force_tts:
        log(f"audio stream found in {src}; copying without TTS")
        return handle_existing_audio(src, out)
    log(f"synthesizing Korean narration ({args.voice}/{VOICE_NAMES.get(args.voice, args.voice)})")
    return handle_synthesis(args, src, out)


if __name__ == "__main__":
    raise SystemExit(main())
