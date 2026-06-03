"""Unit tests for the pure ffmpeg audio-mix graph builder (audio_mix.py).

All assertions run against the PURE builder output; no ffmpeg is invoked here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audio_mix.py"
_SPEC = importlib.util.spec_from_file_location("audio_mix", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
audio_mix = importlib.util.module_from_spec(_SPEC)
sys.modules["audio_mix"] = audio_mix
_SPEC.loader.exec_module(audio_mix)

build_mix_graph = audio_mix.build_mix_graph


def _graph(**kwargs):
    """Build a graph with sensible defaults overridable per case."""
    params = dict(
        narration_dur=10.0,
        bgm_volume=0.16,
        duck=True,
        fade=1.0,
        keep_original=False,
    )
    params.update(kwargs)
    return build_mix_graph(**params)


def test_inputs_narration_plus_bgm() -> None:
    g = _graph(keep_original=False)
    # narration is input 0, bgm is input 1
    assert g.inputs == ["narration", "bgm"]
    # bgm must be stream-looped infinitely on its input
    assert g.bgm_input_args == ["-stream_loop", "-1"]


def test_inputs_with_original_audio() -> None:
    g = _graph(keep_original=True)
    # original video audio becomes a third input
    assert g.inputs == ["narration", "bgm", "original"]


def test_filter_has_volume_param() -> None:
    g = _graph(bgm_volume=0.16)
    assert "volume=0.16" in g.filter_complex
    g2 = _graph(bgm_volume=0.3)
    assert "volume=0.3" in g2.filter_complex


def test_filter_has_loop_trim_and_fades() -> None:
    g = _graph(narration_dur=12.0, fade=1.0)
    fc = g.filter_complex
    # amix trims the looped bed to the narration length
    assert "duration=first" in fc
    # narration not auto-attenuated
    assert "normalize=0" in fc
    # afade in at 0 and out near (dur - fade)
    assert "afade=t=in:st=0" in fc
    assert "afade=t=out" in fc
    assert "st=11.0" in fc  # 12.0 - 1.0 fade


def test_ducking_on_inserts_sidechaincompress() -> None:
    g = _graph(duck=True)
    fc = g.filter_complex
    assert "sidechaincompress=" in fc
    assert "threshold=0.03" in fc
    assert "ratio=8" in fc
    assert "attack=20" in fc
    assert "release=300" in fc


def test_ducking_on_splits_narration_pad_explicitly() -> None:
    g = _graph(duck=True)
    fc = g.filter_complex
    # narration pad is split explicitly (no implicit input-pad auto-split)
    assert "[0:a]asplit=2[nar0][nar1]" in fc
    # one copy keys the sidechain compressor, the other feeds the final amix
    assert "[nar0]sidechaincompress=" in fc
    assert "[nar1]" in fc
    assert "[nar1][bgd]amix=inputs=2:duration=first:normalize=0[mix]" in fc


def test_ducking_off_omits_sidechaincompress() -> None:
    g = _graph(duck=False)
    fc = g.filter_complex
    assert "sidechaincompress" not in fc
    # non-duck path keeps the plain narration pad, no asplit
    assert "asplit" not in fc
    assert "[0:a]" in fc


def test_map_label_is_final_output() -> None:
    g = _graph()
    # final mixed stream is mapped via a labeled pad
    assert g.map_label.startswith("[") and g.map_label.endswith("]")
    assert g.map_label.strip("[]") in g.filter_complex


def test_original_audio_is_mixed_into_bed() -> None:
    g = _graph(keep_original=True)
    fc = g.filter_complex
    # the original input (index 2) is referenced in the graph
    assert "[2:a]" in fc


def test_no_duck_no_original_still_valid_amix() -> None:
    g = _graph(duck=False, keep_original=False)
    fc = g.filter_complex
    # narration + bed mixed with amix, normalize disabled
    assert "amix=inputs=2" in fc
    assert "normalize=0" in fc
