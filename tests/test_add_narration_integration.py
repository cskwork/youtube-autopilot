"""Offline integration test for Stage 6 (add_narration.py).

Uses real ffmpeg but NO network and NO real TTS model: a stub `supertts`
(a tiny python script) writes a short sine WAV per sentence. Asserts the output
MP4 has an audio stream, positive duration, and that the .srt/.ass + CREDITS
behaviors hold.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADD_NARRATION = ROOT / "scripts" / "add_narration.py"


def _have_ffmpeg() -> bool:
    from shutil import which
    return bool(which("ffmpeg") and which("ffprobe"))


pytestmark = pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg/ffprobe required")


# A stub supertts: reads -f <txt> and -o <wav>, emits a 1s sine WAV via ffmpeg.
_FAKE_SUPERTTS = """#!/usr/bin/env python3
import subprocess, sys
args = sys.argv[1:]
txt = out = None
for i, a in enumerate(args):
    if a == "-f": txt = args[i + 1]
    if a == "-o": out = args[i + 1]
assert out, "no -o given"
subprocess.run([
    "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "1.0",
    "-i", "sine=frequency=320:sample_rate=44100", "-ac", "2", out,
], check=True)
"""


def _make_placeholder_video(out: Path, seconds: int = 2) -> Path:
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=navy:s=640x360:d={seconds}:r=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
    ]
    subprocess.run(cmd, check=True)
    return out


def _probe(path: Path, entries: str, stream: str | None = None) -> str:
    cmd = ["ffprobe", "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "default=nw=1:nk=1", str(path)]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def _run_add_narration(tmp_path: Path, extra: list[str]) -> dict:
    video = _make_placeholder_video(tmp_path / "in.mp4")
    fake = tmp_path / "fake_supertts.py"
    fake.write_text(_FAKE_SUPERTTS, encoding="utf-8")
    script = tmp_path / "script.json"
    script.write_text(json.dumps({
        "narration_ko": "첫 번째 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다.",
        "bgm_mood": "calm",
        "key_sentences": ["첫 번째 문장입니다."],
        "youtube": {"title": "t", "description": "d", "tags": ["a"], "category": "22"},
    }, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "narrated.mp4"
    cmd = [
        sys.executable, str(ADD_NARRATION),
        "--in", str(video), "--out", str(out),
        "--script-json", str(script), "--force-tts",
        "--supertts-command", f"{sys.executable} {fake}",
        *extra,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"add_narration failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    line = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")][-1]
    return json.loads(line)


def test_subtitles_and_synth_bgm(tmp_path):
    result = _run_add_narration(tmp_path, ["--subtitles", "--bgm-mood", "calm"])
    out = Path(result["out"])
    assert out.is_file()
    # audio stream present
    assert _probe(out, "stream=codec_type", "a:0") == "audio"
    # positive duration
    assert float(_probe(out, "format=duration")) > 0
    # synth BGM resolved (no network), no attribution required
    assert result["bgm"]["source"] == "synth"
    assert result["bgm"]["attribution"] is None
    # caption sidecars exist and only the key sentence is captioned
    srt = Path(result["subtitles"]["srt"])
    ass = Path(result["subtitles"]["ass"])
    assert srt.is_file() and ass.is_file()
    assert result["subtitles"]["key_count"] == 1
    assert "첫 번째 문장입니다." in srt.read_text(encoding="utf-8")
    assert "두 번째 문장입니다." not in srt.read_text(encoding="utf-8")
    # synth BGM needs no CREDITS file
    assert not (out.parent / "CREDITS.txt").exists()


def test_no_subtitles_no_bgm_keeps_audio(tmp_path):
    result = _run_add_narration(tmp_path, ["--no-subtitles", "--no-bgm"])
    out = Path(result["out"])
    assert out.is_file()
    assert _probe(out, "stream=codec_type", "a:0") == "audio"
    assert float(_probe(out, "format=duration")) > 0
    assert result["bgm"] is None
    assert result["subtitles"] is None
