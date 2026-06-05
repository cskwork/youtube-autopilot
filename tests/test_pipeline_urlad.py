"""Wiring tests for the url-ad workflow in the orchestrator.

Stubs the subprocess-calling stages (ingest/script/visuals/narration/upload) so
no browser/codex/TTS runs, then drives the real run_pipeline (mode=url-ad) and
asserts the gate chain + ordering: a valid run reaches upload, and degraded page
facts hard-stop before the script stage. Pure helpers (idea/storyboard
derivation, ingest adoption, path building) are tested directly.
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


def _good_video(path: Path, seconds: float = 2.0) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=teal:s=320x240:d={seconds}:r=24",
         "-f", "lavfi", "-i", f"sine=frequency=320:sample_rate=44100:d={seconds}",
         "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
        check=True,
    )


_GOOD_FACTS = {
    "url": "https://example.com", "title": "Example", "brand": "Example Inc",
    "value_props": ["No editing", "Paste a URL"], "features": ["120 voices"],
    "cta_text": "Start free", "screenshots": [],
}


def _urlad_args() -> argparse.Namespace:
    return argparse.Namespace(mode="url-ad")


def _install_stubs(monkeypatch, paths, *, facts, video_builder, calls):
    def ingest(args, p):
        paths["page_facts"].parent.mkdir(parents=True, exist_ok=True)
        paths["page_facts"].write_text(json.dumps(facts), encoding="utf-8")
        return paths["page_facts"]

    def script(args, idea_file, p):
        paths["script"].write_text(
            json.dumps({"narration_ko": "안녕하세요. 반갑습니다.", "flow_prompt": "x"}),
            encoding="utf-8",
        )
        return paths["script"]

    def visuals(args, scr, p):
        video_builder(paths["raw_video"])
        return paths["raw_video"]

    def narration(args, raw, scr, p):
        _good_video(paths["narrated_video"])
        return {"out": str(paths["narrated_video"]), "bgm": None}

    def upload(args, video, scr, extra):
        calls["upload"] = True
        return {"video_id": "stub", "studio_url": "http://x", "watch_url": "http://w"}

    monkeypatch.setattr(pipeline, "stage_ingest", ingest)
    monkeypatch.setattr(pipeline, "stage_script", script)
    monkeypatch.setattr(pipeline, "stage_visuals_slideshow", visuals)
    monkeypatch.setattr(pipeline, "stage_narration", narration)
    monkeypatch.setattr(pipeline, "stage_upload", upload)


# --- pure helpers ------------------------------------------------------------

def test_build_paths_urlad_adds_page_facts(tmp_path):
    assert "page_facts" in pipeline.build_paths(tmp_path, "url-ad")
    assert "page_facts" not in pipeline.build_paths(tmp_path)  # idea-video default


def test_stage_ingest_adopts_supplied_facts(tmp_path):
    src = tmp_path / "supplied.json"
    src.write_text(json.dumps(_GOOD_FACTS), encoding="utf-8")
    paths = pipeline.build_paths(tmp_path, "url-ad")
    args = argparse.Namespace(page_facts_json=str(src), url="", aspect_ratio="9:16")
    out = pipeline.stage_ingest(args, paths)
    assert out == paths["page_facts"]
    assert json.loads(out.read_text())["cta_text"] == "Start free"


def test_stage_ingest_requires_url_or_facts(tmp_path):
    paths = pipeline.build_paths(tmp_path, "url-ad")
    args = argparse.Namespace(page_facts_json="", url="  ", aspect_ratio="9:16")
    with pytest.raises(SystemExit, match="requires --url"):
        pipeline.stage_ingest(args, paths)


def test_urlad_idea_storyboard_derives_scenes(tmp_path):
    paths = pipeline.build_paths(tmp_path, "url-ad")
    idea_file = pipeline._urlad_idea_storyboard(_GOOD_FACTS, paths)
    assert json.loads(idea_file.read_text())["title"] == "Example"
    sb = json.loads((paths["storyboard_dir"] / "storyboard.json").read_text())
    # 2 value_props + 1 feature -> 3 scenes
    assert len(sb["scenes"]) == 3


# --- wiring ------------------------------------------------------------------

def test_urlad_happy_path_reaches_upload(tmp_path, monkeypatch):
    paths = pipeline.build_paths(tmp_path, "url-ad")
    calls = {"upload": False}
    _install_stubs(monkeypatch, paths, facts=_GOOD_FACTS, video_builder=_good_video, calls=calls)
    pipeline.run_pipeline(_urlad_args(), paths)
    assert calls["upload"] is True


def test_urlad_bad_page_facts_hard_stops_before_script(tmp_path, monkeypatch):
    paths = pipeline.build_paths(tmp_path, "url-ad")
    calls = {"upload": False}
    bad = {**_GOOD_FACTS, "value_props": []}  # no USP source -> gate must fail
    _install_stubs(monkeypatch, paths, facts=bad, video_builder=_good_video, calls=calls)
    with pytest.raises(SystemExit, match="GATE FAILED after 'ingest_url'"):
        pipeline.run_pipeline(_urlad_args(), paths)
    assert calls["upload"] is False
