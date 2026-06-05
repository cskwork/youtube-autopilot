"""Unit tests for the per-stage verification gates.

Builds tiny ffmpeg fixtures (good / no-audio / silent / truncated / short) and
asserts each gate PASSES a valid artifact and RAISES ``GateError`` on a degraded
one. This is the proof behind "each stage must pass": exit-code-0 is not enough,
the produced artifact must be real.

No network, no TTS; only ffmpeg (skipped if absent).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from shutil import which

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stage_gates.py"
_SPEC = importlib.util.spec_from_file_location("stage_gates", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
stage_gates = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(stage_gates)

GateError = stage_gates.GateError

pytestmark = pytest.mark.skipif(
    not (which("ffmpeg") and which("ffprobe")), reason="ffmpeg/ffprobe required"
)


# --- ffmpeg fixture builders -------------------------------------------------

def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _good_video(path: Path, seconds: float = 2.0) -> Path:
    """A real clip: navy video + an audible 320 Hz tone."""
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=navy:s=320x240:d={seconds}:r=24",
        "-f", "lavfi", "-i", f"sine=frequency=320:sample_rate=44100:d={seconds}",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    )
    return path


def _video_no_audio(path: Path, seconds: float = 2.0) -> Path:
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=navy:s=320x240:d={seconds}:r=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    )
    return path


def _silent_video(path: Path, seconds: float = 2.0) -> Path:
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=navy:s=320x240:d={seconds}:r=24",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    )
    return path


# --- video gate --------------------------------------------------------------

def test_gate_video_passes_good_clip(tmp_path):
    info = stage_gates.gate_video(_good_video(tmp_path / "g.mp4"))
    assert info["duration"] >= 1.0
    assert info["bytes"] > 1024


def test_gate_video_fails_missing_file(tmp_path):
    with pytest.raises(GateError, match="missing output file"):
        stage_gates.gate_video(tmp_path / "nope.mp4")


def test_gate_video_fails_tiny_file(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video")
    with pytest.raises(GateError, match="too small"):
        stage_gates.gate_video(junk)


def test_gate_video_fails_short_duration(tmp_path):
    short = _good_video(tmp_path / "short.mp4", seconds=0.4)
    with pytest.raises(GateError, match="below minimum"):
        stage_gates.gate_video(short, min_duration=1.0)


# --- narration gate (the "audio gen must pass" teeth) ------------------------

def test_gate_narration_passes_audible_clip(tmp_path):
    info = stage_gates.gate_narration(_good_video(tmp_path / "n.mp4"))
    assert info["mean_volume_db"] > stage_gates.DEFAULT_SILENCE_DB


def test_gate_narration_fails_when_no_audio(tmp_path):
    with pytest.raises(GateError, match="no audio stream"):
        stage_gates.gate_narration(_video_no_audio(tmp_path / "v.mp4"))


def test_gate_narration_fails_on_silence(tmp_path):
    with pytest.raises(GateError, match="silent"):
        stage_gates.gate_narration(_silent_video(tmp_path / "s.mp4"))


def test_mean_volume_audible_vs_silent(tmp_path):
    audible = stage_gates.mean_volume_db(_good_video(tmp_path / "a.mp4"))
    silent = stage_gates.mean_volume_db(_silent_video(tmp_path / "z.mp4"))
    assert audible > stage_gates.DEFAULT_SILENCE_DB >= silent


# --- JSON gates --------------------------------------------------------------

def test_gate_ideas_passes_and_fails(tmp_path):
    good = tmp_path / "ideas.json"
    good.write_text(json.dumps({"ideas": [{"title": "a"}, {"title": "b"}]}), encoding="utf-8")
    assert stage_gates.gate_ideas(good, min_count=2)["count"] == 2
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"ideas": []}), encoding="utf-8")
    with pytest.raises(GateError, match="ideas"):
        stage_gates.gate_ideas(empty, min_count=1)


def test_gate_script_passes_and_fails(tmp_path):
    good = tmp_path / "script.json"
    good.write_text(json.dumps({"narration_ko": "안녕하세요.", "flow_prompt": "cinematic"}),
                    encoding="utf-8")
    assert stage_gates.gate_script(good)["narration_chars"] > 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"narration_ko": "  ", "flow_prompt": "x"}), encoding="utf-8")
    with pytest.raises(GateError, match="narration_ko"):
        stage_gates.gate_script(bad)
    no_flow = tmp_path / "noflow.json"
    no_flow.write_text(json.dumps({"narration_ko": "안녕."}), encoding="utf-8")
    with pytest.raises(GateError, match="flow_prompt"):
        stage_gates.gate_script(no_flow)


def test_gate_storyboard_passes_and_fails(tmp_path):
    sb = tmp_path / "storyboard"
    sb.mkdir()
    (sb / "storyboard.json").write_text(json.dumps({"scenes": [1, 2]}), encoding="utf-8")
    # too-small frame -> fail
    (sb / "scene_01.png").write_bytes(b"x")
    with pytest.raises(GateError, match="too small"):
        stage_gates.gate_storyboard(sb, min_scenes=1)
    # a real-sized frame -> pass
    (sb / "scene_01.png").write_bytes(b"P" * 2048)
    assert stage_gates.gate_storyboard(sb, min_scenes=1)["frames"] == 1
    # missing storyboard.json -> fail
    (sb / "storyboard.json").unlink()
    with pytest.raises(GateError, match="missing file"):
        stage_gates.gate_storyboard(sb, min_scenes=1)


def test_gate_storyboard_fails_when_no_frames(tmp_path):
    sb = tmp_path / "sb2"
    sb.mkdir()
    (sb / "storyboard.json").write_text(json.dumps({"scenes": []}), encoding="utf-8")
    with pytest.raises(GateError, match="scene_"):
        stage_gates.gate_storyboard(sb, min_scenes=1)


# --- page-facts gate (URL-AD Stage 0 grounding) ------------------------------

def test_gate_page_facts_passes_and_fails(tmp_path):
    good = tmp_path / "page_facts.json"
    good.write_text(json.dumps({
        "url": "https://example.com",
        "title": "Example Product",
        "value_props": ["Save hours of editing", "No recording needed"],
        "cta_text": "Start free",
    }), encoding="utf-8")
    assert stage_gates.gate_page_facts(good)["value_props"] == 2
    # empty value_props -> no USP source -> fail
    no_props = tmp_path / "noprops.json"
    no_props.write_text(json.dumps({
        "url": "https://example.com", "title": "X",
        "value_props": [], "cta_text": "Go",
    }), encoding="utf-8")
    with pytest.raises(GateError, match="value_props"):
        stage_gates.gate_page_facts(no_props)
    # blank cta_text -> no CTA slot -> fail
    no_cta = tmp_path / "nocta.json"
    no_cta.write_text(json.dumps({
        "url": "https://example.com", "title": "X",
        "value_props": ["a"], "cta_text": "   ",
    }), encoding="utf-8")
    with pytest.raises(GateError, match="cta_text"):
        stage_gates.gate_page_facts(no_cta)


def test_gate_page_facts_fails_non_object(tmp_path):
    arr = tmp_path / "arr.json"
    arr.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(GateError, match="object"):
        stage_gates.gate_page_facts(arr)
