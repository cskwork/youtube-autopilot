"""Integration test for the orchestrator's per-stage gate wiring.

Stubs each stage producer so it emits a controlled artifact (good or degraded),
then runs the real ``run_pipeline`` and asserts that a degraded artifact
hard-stops the chain BEFORE upload — proving "each stage must pass" is wired in,
not just available. No codex / Flow / TTS / network; only ffmpeg for fixtures.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path
from shutil import which

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "auto_youtube_pipeline.py"
_SPEC = importlib.util.spec_from_file_location("auto_youtube_pipeline", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
pipeline = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pipeline)

pytestmark = pytest.mark.skipif(
    not (which("ffmpeg") and which("ffprobe")), reason="ffmpeg/ffprobe required"
)


# --- ffmpeg fixtures ---------------------------------------------------------

def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _good_video(path: Path, seconds: float = 2.0) -> None:
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=navy:s=320x240:d={seconds}:r=24",
        "-f", "lavfi", "-i", f"sine=frequency=320:sample_rate=44100:d={seconds}",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    )


def _silent_video(path: Path, seconds: float = 2.0) -> None:
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=navy:s=320x240:d={seconds}:r=24",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    )


# --- stubbed stages ----------------------------------------------------------

def _install_stub_stages(monkeypatch, paths, *, video_builder, narration_builder, calls):
    """Replace each stage producer with one that drops a controlled artifact."""
    def harvest(args, p):
        paths["ideas"].write_text(json.dumps({"ideas": [{"title": "t"}]}), encoding="utf-8")
        return paths["ideas"]

    def storyboard(args, ideas, p):
        d = paths["storyboard_dir"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "storyboard.json").write_text(json.dumps({"scenes": [1]}), encoding="utf-8")
        (d / "scene_01.png").write_bytes(b"P" * 4096)
        return d

    def script(args, idea_file, p):
        paths["script"].write_text(
            json.dumps({"narration_ko": "안녕하세요. 반갑습니다.", "flow_prompt": "cinematic"}),
            encoding="utf-8",
        )
        return paths["script"]

    def video(args, scr, p):
        video_builder(paths["raw_video"])
        return paths["raw_video"]

    def delogo(raw, p):
        _good_video(paths["delogo_video"])
        return {"box": [1, 1, 10, 10]}

    def narration(args, delogo_path, scr, p):
        narration_builder(paths["narrated_video"])
        return {"out": str(paths["narrated_video"]), "bgm": None, "subtitles": None}

    def upload(args, video_path, scr, extra):
        calls["upload"] = True
        return {"video_id": "stub", "studio_url": "http://x", "watch_url": "http://w"}

    monkeypatch.setattr(pipeline, "stage_harvest", harvest)
    monkeypatch.setattr(pipeline, "stage_storyboard", storyboard)
    monkeypatch.setattr(pipeline, "stage_script", script)
    monkeypatch.setattr(pipeline, "stage_video", video)
    monkeypatch.setattr(pipeline, "stage_delogo", delogo)
    monkeypatch.setattr(pipeline, "stage_narration", narration)
    monkeypatch.setattr(pipeline, "stage_upload", upload)


def _args(idea_index: int = 0) -> argparse.Namespace:
    return argparse.Namespace(idea_index=idea_index)


def _run(tmp_path, monkeypatch, *, video_builder, narration_builder):
    paths = pipeline.build_paths(tmp_path)
    calls: dict[str, bool] = {"upload": False}
    _install_stub_stages(monkeypatch, paths, video_builder=video_builder,
                         narration_builder=narration_builder, calls=calls)
    pipeline.run_pipeline(_args(), paths)
    return calls


# --- the proofs --------------------------------------------------------------

def test_happy_path_reaches_upload(tmp_path, monkeypatch):
    calls = _run(tmp_path, monkeypatch,
                 video_builder=_good_video, narration_builder=_good_video)
    assert calls["upload"] is True


def test_degraded_video_hard_stops_before_upload(tmp_path, monkeypatch):
    def junk(path: Path) -> None:
        path.write_bytes(b"not a video")  # ok:true contract, but unusable artifact

    paths = pipeline.build_paths(tmp_path)
    calls: dict[str, bool] = {"upload": False}
    _install_stub_stages(monkeypatch, paths, video_builder=junk,
                         narration_builder=_good_video, calls=calls)
    with pytest.raises(SystemExit, match="GATE FAILED after 'generate_video'"):
        pipeline.run_pipeline(_args(), paths)
    assert calls["upload"] is False


def test_silent_narration_hard_stops_before_upload(tmp_path, monkeypatch):
    paths = pipeline.build_paths(tmp_path)
    calls: dict[str, bool] = {"upload": False}
    _install_stub_stages(monkeypatch, paths, video_builder=_good_video,
                         narration_builder=_silent_video, calls=calls)
    with pytest.raises(SystemExit, match="GATE FAILED after 'add_narration'"):
        pipeline.run_pipeline(_args(), paths)
    assert calls["upload"] is False
