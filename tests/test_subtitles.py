"""Unit tests for sentence segmentation, timing assembly, and caption files."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "subtitles.py"
_SPEC = importlib.util.spec_from_file_location("subtitles", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
subtitles = importlib.util.module_from_spec(_SPEC)
sys.modules["subtitles"] = subtitles
_SPEC.loader.exec_module(subtitles)

split_sentences = subtitles.split_sentences
assemble_segments = subtitles.assemble_segments
select_key_indices = subtitles.select_key_indices
build_srt = subtitles.build_srt
build_ass = subtitles.build_ass
burn_vf = subtitles.burn_vf


# --- segmentation ------------------------------------------------------------

def test_split_korean_terminators() -> None:
    text = "안녕하세요. 오늘은 날씨가 좋아요! 정말 그런가요? 음… 그렇네요。"
    out = split_sentences(text)
    assert out == [
        "안녕하세요.",
        "오늘은 날씨가 좋아요!",
        "정말 그런가요?",
        "음…",
        "그렇네요。",
    ]


def test_split_on_newlines_and_drops_empties() -> None:
    text = "첫 문장.\n\n두 번째 문장.\n   \n세 번째."
    out = split_sentences(text)
    assert out == ["첫 문장.", "두 번째 문장.", "세 번째."]


def test_split_strips_whitespace() -> None:
    out = split_sentences("  여백 있는 문장.  ")
    assert out == ["여백 있는 문장."]


def test_split_empty_returns_empty() -> None:
    assert split_sentences("   ") == []


# --- timing assembly ---------------------------------------------------------

def test_assemble_segments_accumulates_offsets() -> None:
    sentences = ["가.", "나.", "다."]
    durs = [2.0, 3.0, 1.5]
    segs = assemble_segments(sentences, ["a.wav", "b.wav", "c.wav"], durs)
    assert [s.start for s in segs] == [0.0, 2.0, 5.0]
    assert [s.end for s in segs] == [2.0, 5.0, 6.5]
    assert [s.text for s in segs] == sentences
    assert [s.wav for s in segs] == ["a.wav", "b.wav", "c.wav"]


# --- key selection -----------------------------------------------------------

def test_key_verbatim_match_whitespace_robust() -> None:
    sentences = ["첫 문장.", "둘째 문장.", "셋째 문장."]
    keys = ["둘째   문장.", "셋째 문장."]
    idx = select_key_indices(sentences, keys, max_count=10)
    assert idx == [1, 2]


def test_key_heuristic_when_absent() -> None:
    sentences = [f"문장{i}." for i in range(10)]
    idx = select_key_indices(sentences, None, max_count=10)
    # first sentence always captioned, then roughly every 3rd
    assert idx[0] == 0
    assert idx == sorted(idx)
    assert all(0 <= i < 10 for i in idx)
    assert 1 < len(idx) < 10  # sparse, not every sentence


def test_key_heuristic_when_empty_list() -> None:
    sentences = [f"문장{i}." for i in range(6)]
    idx = select_key_indices(sentences, [], max_count=10)
    assert idx[0] == 0
    assert len(idx) < 6


def test_key_respects_max_count() -> None:
    sentences = [f"문장{i}." for i in range(30)]
    idx = select_key_indices(sentences, None, max_count=3)
    assert len(idx) <= 3


# --- caption files -----------------------------------------------------------

def _segs():
    sentences = ["첫 문장.", "둘째 문장.", "셋째 문장."]
    return assemble_segments(sentences, ["a.wav", "b.wav", "c.wav"], [2.0, 3.0, 1.5])


def test_srt_only_captions_key_indices() -> None:
    segs = _segs()
    srt = build_srt(segs, [0, 2])
    assert "첫 문장." in srt
    assert "셋째 문장." in srt
    assert "둘째 문장." not in srt  # index 1 not a key
    # SRT timestamp format HH:MM:SS,mmm
    assert "00:00:00,000 --> 00:00:02,000" in srt
    # second captioned block uses index 2 timing (start 5.0)
    assert "00:00:05,000 --> 00:00:06,500" in srt


def test_srt_sequential_numbering() -> None:
    segs = _segs()
    srt = build_srt(segs, [0, 1, 2])
    lines = [ln for ln in srt.splitlines() if ln.strip().isdigit()]
    assert lines[:3] == ["1", "2", "3"]


def test_ass_has_style_and_only_key_dialogue() -> None:
    segs = _segs()
    ass = build_ass(segs, [0, 2])
    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass
    assert "Dialogue:" in ass
    # ASS time format H:MM:SS.cc
    assert "0:00:00.00" in ass
    assert ass.count("Dialogue:") == 2  # only the two key indices
    assert "둘째 문장." not in ass


def test_burn_vf_escapes_path() -> None:
    vf = burn_vf("/tmp/some dir/captions.ass")
    assert vf.startswith("ass=")
    assert "captions.ass" in vf
