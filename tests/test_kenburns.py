"""Unit tests for the Ken-Burns clip filter graph (fit decision)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_kenburns_clip.py"
_SPEC = importlib.util.spec_from_file_location("build_kenburns_clip", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
kenburns = importlib.util.module_from_spec(_SPEC)
sys.modules["build_kenburns_clip"] = kenburns
_SPEC.loader.exec_module(kenburns)


def test_tall_source_fits_by_height() -> None:
    vf = kenburns.build_filter(1080, 1920, 3.0, 30, False, src_aspect=720 / 1280)
    assert f"scale=-2:{int(1920 * 0.94)}[fg]" in vf


def test_wide_source_fits_by_width() -> None:
    # A wide content crop (e.g. 720x330 card region) must fit the canvas WIDTH;
    # height-fit would blow it past the frame and show only a mushy center.
    vf = kenburns.build_filter(1080, 1920, 3.0, 30, False, src_aspect=720 / 330)
    assert f"scale={int(1080 * 0.94)}:-2[fg]" in vf


def test_unknown_aspect_keeps_height_fit() -> None:
    vf = kenburns.build_filter(1080, 1920, 3.0, 30, False)
    assert f"scale=-2:{int(1920 * 0.94)}[fg]" in vf
