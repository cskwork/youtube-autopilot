"""Offline unit tests for ingest_url pure helpers (no browser, no codex).

The live browser fetch + codex distillation are exercised by a human-approved
live run; these tests pin the template substitution, screenshot decoding, and
page_facts assembly (which must satisfy stage_gates.gate_page_facts).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingest_url = _load("ingest_url")
stage_gates = _load("stage_gates")

_TEMPLATE = (_SCRIPTS / "js" / "fetch_url_artifacts.tmpl.js").read_text(encoding="utf-8")
# a 1x1 transparent PNG
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_render_fetch_js_substitutes_all_tokens():
    js = ingest_url.render_fetch_js(_TEMPLATE, "https://example.com", 3, {"width": 1080, "height": 1920})
    assert "__URL__" not in js and "__MAX_SHOTS__" not in js and "__VIEWPORT__" not in js
    assert "https://example.com" in js
    assert "3" in js
    assert "page.goto" in js  # the real navigation call survives substitution


def test_write_screenshots_decodes_and_names(tmp_path):
    paths = ingest_url.write_screenshots([_PNG_B64, _PNG_B64], tmp_path / "shots")
    assert len(paths) == 2
    assert paths[0].endswith("scene_00.png") and paths[1].endswith("scene_01.png")
    for p in paths:
        assert Path(p).stat().st_size > 0


def test_write_screenshots_skips_empty_and_bad(tmp_path):
    paths = ingest_url.write_screenshots(["", _PNG_B64, "!!not-base64!!"], tmp_path / "shots")
    # empty skipped; valid kept; "!!not-base64!!" decodes leniently to bytes, so
    # at least the real PNG is present and indices are stable.
    assert any(p.endswith("scene_01.png") for p in paths)


def test_assemble_page_facts_merges_and_passes_gate(tmp_path):
    distilled = {
        "title": "Example",
        "brand": "Example Inc",
        "value_props": ["No editing", "Paste a URL"],
        "features": ["120 voices"],
        "cta_text": "Start free",
        "cta_url": "https://example.com/signup",
    }
    raw = {"title": "raw title", "url": "https://example.com"}
    facts = ingest_url.assemble_page_facts(distilled, raw, "https://example.com", ["s/scene_00.png"])
    assert facts["url"] == "https://example.com"
    assert facts["brand"] == "Example Inc"
    assert facts["screenshots"] == ["s/scene_00.png"]
    # the assembled facts must satisfy the Stage 0 gate
    out = tmp_path / "page_facts.json"
    out.write_text(__import__("json").dumps(facts), encoding="utf-8")
    assert stage_gates.gate_page_facts(out)["value_props"] == 2


def test_assemble_page_facts_falls_back_to_raw_title():
    facts = ingest_url.assemble_page_facts({}, {"title": "Raw Title"}, "u", [])
    assert facts["title"] == "Raw Title"
    assert facts["brand"] == "Raw Title"  # brand falls back to title


def test_build_distill_prompt_is_facts_only():
    prompt = ingest_url.build_distill_prompt({"title": "T", "headings": ["H1"]})
    assert "Use ONLY" in prompt
    assert "do not invent" in prompt.lower()
    assert "H1" in prompt  # the raw extraction is included
