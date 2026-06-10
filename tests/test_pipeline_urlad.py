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


_AD_SCRIPT = {
    "narration_ko": (
        "영상 광고, 3초면 끝나요. "
        "링크만 붙여넣으면 페이지가 그대로 광고가 됩니다. "
        "편집도 녹화도 필요 없습니다. "
        "지금 무료로 시작하세요."
    ),
    "flow_prompt": "x",
    "key_sentences": ["영상 광고, 3초면 끝나요.", "지금 무료로 시작하세요."],
}


def _install_stubs(monkeypatch, paths, *, facts, video_builder, calls,
                   script_data=None):
    def ingest(args, p):
        paths["page_facts"].parent.mkdir(parents=True, exist_ok=True)
        paths["page_facts"].write_text(json.dumps(facts), encoding="utf-8")
        return paths["page_facts"]

    def script(args, idea_file, p):
        paths["script"].write_text(
            json.dumps(script_data or _AD_SCRIPT, ensure_ascii=False),
            encoding="utf-8",
        )
        return paths["script"]

    def visuals(args, scr, p):
        video_builder(paths["raw_video"])
        return paths["raw_video"]

    def narration(args, raw, scr, p, caption_args=None):
        calls["caption_args"] = caption_args
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
    # short-form: one scene per value prop only (features do NOT spawn scenes)
    assert len(sb["scenes"]) == 2


def test_urlad_idea_storyboard_caps_scenes_at_five(tmp_path):
    paths = pipeline.build_paths(tmp_path, "url-ad")
    facts = {**_GOOD_FACTS, "value_props": [f"prop {i}" for i in range(9)]}
    pipeline._urlad_idea_storyboard(facts, paths)
    sb = json.loads((paths["storyboard_dir"] / "storyboard.json").read_text())
    assert len(sb["scenes"]) == 5


# --- wiring ------------------------------------------------------------------

def test_urlad_happy_path_reaches_upload(tmp_path, monkeypatch):
    paths = pipeline.build_paths(tmp_path, "url-ad")
    calls: dict[str, object] = {"upload": False}
    _install_stubs(monkeypatch, paths, facts=_GOOD_FACTS, video_builder=_good_video, calls=calls)
    pipeline.run_pipeline(_urlad_args(), paths)
    assert calls["upload"] is True
    # the url-ad chain always requests full-coverage captions
    caption_args = list(calls["caption_args"])  # type: ignore[call-overload]
    assert caption_args[:2] == ["--caption-coverage", "all"]


def test_urlad_bad_page_facts_hard_stops_before_script(tmp_path, monkeypatch):
    paths = pipeline.build_paths(tmp_path, "url-ad")
    calls = {"upload": False}
    bad = {**_GOOD_FACTS, "value_props": []}  # no USP source -> gate must fail
    _install_stubs(monkeypatch, paths, facts=bad, video_builder=_good_video, calls=calls)
    with pytest.raises(SystemExit, match="GATE FAILED after 'ingest_url'"):
        pipeline.run_pipeline(_urlad_args(), paths)
    assert calls["upload"] is False


def test_urlad_weak_ad_script_hard_stops_before_visuals(tmp_path, monkeypatch):
    """A script without key_sentences (no captionable hook/CTA) fails ad_quality."""
    paths = pipeline.build_paths(tmp_path, "url-ad")
    calls = {"upload": False}
    weak = {**_AD_SCRIPT, "key_sentences": []}
    _install_stubs(monkeypatch, paths, facts=_GOOD_FACTS, video_builder=_good_video,
                   calls=calls, script_data=weak)
    with pytest.raises(SystemExit, match="GATE FAILED after 'ad_quality'"):
        pipeline.run_pipeline(_urlad_args(), paths)
    assert calls["upload"] is False


def test_urlad_narration_gets_full_captions_and_brand_colors(tmp_path, monkeypatch):
    """url-ad narration must caption EVERY sentence and pass brand accents."""
    captured: dict[str, list[str]] = {}

    def fake_run_stage(name, cmd):
        captured[name] = [str(c) for c in cmd]
        return {}

    monkeypatch.setattr(pipeline, "run_stage", fake_run_stage)
    args = argparse.Namespace(voice="F1", no_bgm=True, no_subtitles=False,
                              allow_synth_bgm=False, bgm="")
    pipeline.stage_narration(
        args, tmp_path / "in.mp4", tmp_path / "script.json",
        {"narrated_video": tmp_path / "narrated.mp4"},
        caption_args=["--caption-coverage", "all", "--brand-colors", "#e94560"],
    )
    cmd = captured["add_narration"]
    assert "--caption-coverage" in cmd and "all" in cmd
    assert "--brand-colors" in cmd and "#e94560" in cmd


def test_urlad_caption_args_derives_from_page_facts():
    """Coverage is always 'all'; brand colors flow through when present."""
    with_colors = pipeline._urlad_caption_args(
        {**_GOOD_FACTS, "brand_colors": ["#1a1a2e", "#e94560"]})
    assert with_colors[:2] == ["--caption-coverage", "all"]
    assert "--brand-colors" in with_colors
    assert "#1a1a2e,#e94560" in with_colors
    without = pipeline._urlad_caption_args(_GOOD_FACTS)
    assert without == ["--caption-coverage", "all"]
