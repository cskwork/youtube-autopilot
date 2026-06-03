"""Unit tests for the Stage 5 delogo box geometry helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "remove_logo.py"
_SPEC = importlib.util.spec_from_file_location("remove_logo", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
remove_logo = importlib.util.module_from_spec(_SPEC)
sys.modules["remove_logo"] = remove_logo
_SPEC.loader.exec_module(remove_logo)

compute_box = remove_logo.compute_box
parse_box = remove_logo.parse_box

FRAMES = [(1280, 720), (1080, 1920)]
CORNERS = ("bottom-right", "bottom-left", "top-right", "top-left")
MARGIN = 12
W_FRAC = 0.20
H_FRAC = 0.10


def _assert_inside(box: tuple[int, int, int, int], width: int, height: int) -> None:
    x, y, w, h = box
    assert w >= 1 and h >= 1
    assert x >= 1 and y >= 1
    assert x + w <= width - 1
    assert y + h <= height - 1


@pytest.mark.parametrize("width,height", FRAMES)
@pytest.mark.parametrize("corner", CORNERS)
def test_box_inside_frame(width: int, height: int, corner: str) -> None:
    box = compute_box(width, height, corner, MARGIN, W_FRAC, H_FRAC)
    _assert_inside(box, width, height)


@pytest.mark.parametrize("width,height", FRAMES)
@pytest.mark.parametrize("corner", CORNERS)
def test_box_lands_in_requested_corner(width: int, height: int, corner: str) -> None:
    x, y, w, h = compute_box(width, height, corner, MARGIN, W_FRAC, H_FRAC)
    mid_x = width / 2
    mid_y = height / 2
    box_center_x = x + w / 2
    box_center_y = y + h / 2
    if corner.endswith("right"):
        assert box_center_x > mid_x
    else:
        assert box_center_x < mid_x
    if corner.startswith("bottom"):
        assert box_center_y > mid_y
    else:
        assert box_center_y < mid_y


@pytest.mark.parametrize("width,height", FRAMES)
def test_right_corners_respect_margin(width: int, height: int) -> None:
    x, y, w, h = compute_box(width, height, "bottom-right", MARGIN, W_FRAC, H_FRAC)
    assert x + w == width - 1 - MARGIN
    assert y + h == height - 1 - MARGIN


@pytest.mark.parametrize("width,height", FRAMES)
def test_left_top_corners_respect_margin(width: int, height: int) -> None:
    x, y, _, _ = compute_box(width, height, "top-left", MARGIN, W_FRAC, H_FRAC)
    assert x == 1 + MARGIN
    assert y == 1 + MARGIN


def test_fraction_sizing() -> None:
    x, y, w, h = compute_box(1280, 720, "bottom-right", MARGIN, W_FRAC, H_FRAC)
    assert w == round(1280 * W_FRAC)
    assert h == round(720 * H_FRAC)


def test_explicit_box_parsing_wins() -> None:
    box = parse_box("50:60:100:40", 1280, 720)
    assert box == (50, 60, 100, 40)
    _assert_inside(box, 1280, 720)


def test_explicit_box_rejects_out_of_bounds() -> None:
    with pytest.raises(SystemExit):
        parse_box("1200:60:200:40", 1280, 720)


def test_explicit_box_rejects_bad_shape() -> None:
    with pytest.raises(SystemExit):
        parse_box("1:2:3", 1280, 720)


def test_explicit_box_rejects_non_integer() -> None:
    with pytest.raises(SystemExit):
        parse_box("a:b:c:d", 1280, 720)
