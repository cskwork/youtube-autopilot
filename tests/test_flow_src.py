"""Unit tests for google_flow_cli._new_video_src: it must return the NEWEST clip
that appeared after this submit (Flow lists newest-first), never a stale tile."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "google_flow_cli.py"
_SPEC = importlib.util.spec_from_file_location("google_flow_cli", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
gfc = importlib.util.module_from_spec(_SPEC)
sys.modules["google_flow_cli"] = gfc
_SPEC.loader.exec_module(gfc)

new_video_src = gfc._new_video_src


def test_returns_newest_front_source_not_stale_tail() -> None:
    # newest-first list: NEW is index 0; old1/old2 are the pre-submit baseline;
    # STALE is an old tile that happens to be missing from an incomplete baseline
    # and is also echoed in status['src'] (the bug that grabbed it before).
    status = {
        "video_srcs": ["NEW", "old1", "old2", "STALE"],
        "src": "STALE",
        "generating": False,
        "dur": 8,
        "videos": 4,
    }
    baseline = {"old1", "old2"}
    assert new_video_src(status, baseline) == "NEW"


def test_returns_empty_when_nothing_new() -> None:
    status = {"video_srcs": ["old1", "old2"], "src": "old1", "videos": 2}
    assert new_video_src(status, {"old1", "old2"}) == ""


def test_falls_back_to_src_when_list_empty() -> None:
    status = {"video_srcs": [], "src": "NEW", "videos": 1}
    assert new_video_src(status, set()) == "NEW"
