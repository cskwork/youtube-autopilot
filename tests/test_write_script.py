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
