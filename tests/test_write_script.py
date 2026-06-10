"""Unit tests for write_script.validate() (Stage 3 result validation).

Imports validate() directly; no codex CLI is invoked. validate() raises
SystemExit on any contract violation and returns None on a valid result.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "write_script.py"
_SPEC = importlib.util.spec_from_file_location("write_script", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
write_script = importlib.util.module_from_spec(_SPEC)
sys.modules["write_script"] = write_script
_SPEC.loader.exec_module(write_script)

validate = write_script.validate


def _valid_result() -> dict:
    """A complete, valid Stage 3 result the validator must accept."""
    return {
        "narration_ko": "첫 번째 문장입니다.",
        "flow_prompt": "a cinematic prompt",
        "scene_prompts": ["scene one", "scene two"],
        "bgm_mood": "calm uplifting ambient",
        "key_sentences": ["첫 번째 문장입니다."],
        "youtube": {
            "title": "제목",
            "description": "설명",
            "tags": ["calm", "study"],
            "category": "22",
        },
    }


def test_validate_passes_on_full_valid_result() -> None:
    # returns None (no raise) on a complete valid result
    assert validate(_valid_result()) is None


def test_validate_raises_when_bgm_mood_missing() -> None:
    result = _valid_result()
    del result["bgm_mood"]
    with pytest.raises(SystemExit):
        validate(result)


def test_validate_raises_when_bgm_mood_empty() -> None:
    result = _valid_result()
    result["bgm_mood"] = "   "
    with pytest.raises(SystemExit):
        validate(result)


def test_validate_raises_when_key_sentences_missing() -> None:
    result = _valid_result()
    del result["key_sentences"]
    with pytest.raises(SystemExit):
        validate(result)


def test_validate_raises_when_key_sentences_not_a_list() -> None:
    result = _valid_result()
    result["key_sentences"] = "첫 번째 문장입니다."
    with pytest.raises(SystemExit):
        validate(result)


def test_validate_accepts_empty_key_sentences_list() -> None:
    # an empty list is still a list; the contract only requires the array type
    result = _valid_result()
    result["key_sentences"] = []
    assert validate(result) is None


# --- build_prompt: url-ad grounding + aspect note ----------------------------

_IDEA = {"title": "홈카페 레시피"}
_STORYBOARD = {"scenes": [{"n": 1, "visual": "a"}, {"n": 2, "visual": "b"}]}
_SCENES = _STORYBOARD["scenes"]

_PAGE_FACTS = {
    "url": "https://example.com",
    "title": "Example — make videos from a URL",
    "brand": "Example",
    "value_props": ["No editing required", "Paste a URL"],
    "features": ["120 voices", "Multi-format export"],
    "cta_text": "Start free",
}


def test_build_prompt_plain_has_no_grounding() -> None:
    out = write_script.build_prompt(_IDEA, _STORYBOARD, _SCENES, "ko", 8)
    assert "MARKETING GROUNDING" not in out
    assert "narration_ko" in out  # base contract intact


def test_build_prompt_grounded_includes_facts_and_structure() -> None:
    out = write_script.build_prompt(
        _IDEA, _STORYBOARD, _SCENES, "ko", 8,
        page_facts=_PAGE_FACTS, aspect_ratio="9:16",
    )
    assert "MARKETING GROUNDING" in out
    assert "Example" in out                 # brand/title
    assert "No editing required" in out      # a value prop
    assert "Start free" in out               # the CTA
    assert "HOOK" in out and "CALL TO ACTION" in out
    assert "Do not invent" in out            # grounding guardrail
    assert "VERTICAL" in out                 # 9:16 format note
    assert "key_sentences" in out            # base contract still present


def test_build_prompt_aspect_landscape_note() -> None:
    out = write_script.build_prompt(_IDEA, _STORYBOARD, _SCENES, "ko", 8, aspect_ratio="16:9")
    assert "VERTICAL" not in out
    assert "16:9" in out


def test_build_prompt_grounded_minimal_facts() -> None:
    facts = {"url": "u", "title": "T", "value_props": ["only one"], "cta_text": "Go"}
    out = write_script.build_prompt(_IDEA, _STORYBOARD, _SCENES, "ko", 8, page_facts=facts)
    assert "only one" in out
    assert "Go" in out


def test_build_prompt_style_direction_injected() -> None:
    """A routed creative direction (references/ad-creative.md) reaches codex."""
    out = write_script.build_prompt(
        _IDEA, _STORYBOARD, _SCENES, "ko", 8, page_facts=_PAGE_FACTS,
        style_direction="problem-solution: open on the pain, resolve with the product",
    )
    assert "CREATIVE DIRECTION" in out
    assert "open on the pain" in out


def test_build_prompt_no_style_direction_block_by_default() -> None:
    out = write_script.build_prompt(
        _IDEA, _STORYBOARD, _SCENES, "ko", 8, page_facts=_PAGE_FACTS)
    assert "CREATIVE DIRECTION" not in out
