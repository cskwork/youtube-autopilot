"""Unit tests for BGM resolution order, license filtering, and attribution.

All network access is mocked; no real Jamendo call or download occurs.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bgm_library.py"
_SPEC = importlib.util.spec_from_file_location("bgm_library", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
bgm_library = importlib.util.module_from_spec(_SPEC)
sys.modules["bgm_library"] = bgm_library
_SPEC.loader.exec_module(bgm_library)

resolve = bgm_library.resolve


def _canned_tracks(license_url: str):
    """A Jamendo API response with one track at the given license URL."""
    return {
        "results": [
            {
                "name": "Gentle Morning",
                "artist_name": "Test Artist",
                "audiodownload": "https://example.com/track.mp3",
                "license_ccurl": license_url,
                "musicinfo": {},
            }
        ]
    }


def _mock_jamendo(monkeypatch, payload: dict, *, download=True):
    """Patch urlopen to return canned JSON and urlretrieve to write a fake file."""
    def fake_urlopen(req, timeout=None):
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    def fake_urlretrieve(url, dest):
        Path(dest).write_bytes(b"FAKEMP3DATA")
        return dest, None

    monkeypatch.setattr(bgm_library.urllib.request, "urlopen", fake_urlopen)
    if download:
        monkeypatch.setattr(bgm_library.urllib.request, "urlretrieve", fake_urlretrieve)


# --- explicit override -------------------------------------------------------

def test_explicit_path_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    explicit = tmp_path / "mytrack.mp3"
    explicit.write_bytes(b"data")
    res = resolve("calm", explicit_path=str(explicit), cache_dir=tmp_path / "cache",
                  duration=10.0, work_dir=tmp_path / "work")
    assert res.path == str(explicit)
    assert res.source == "explicit"
    assert res.attribution is None


# --- cache hit ---------------------------------------------------------------

def test_cache_hit_before_online(tmp_path, monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "should-not-be-used")
    cache = tmp_path / "cache"
    cache.mkdir(parents=True)
    slug = bgm_library.mood_slug("Calm Ambient")
    cached = cache / f"{slug}.mp3"
    cached.write_bytes(b"cachedaudio")
    # urlopen must NOT be called; make it raise if it is
    monkeypatch.setattr(bgm_library.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network hit")))
    res = resolve("Calm Ambient", cache_dir=cache, duration=10.0, work_dir=tmp_path / "work")
    assert res.path == str(cached)
    assert res.source == "cache"


# --- jamendo online ----------------------------------------------------------

def test_jamendo_accepts_cc_by_and_formats_attribution(tmp_path, monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "key123")
    _mock_jamendo(monkeypatch, _canned_tracks("http://creativecommons.org/licenses/by/3.0/"))
    res = resolve("calm", cache_dir=tmp_path / "cache", duration=10.0, work_dir=tmp_path / "work")
    assert res.source == "jamendo"
    assert "CC-BY" in res.license or "by" in res.license.lower()
    assert res.attribution is not None
    assert "Gentle Morning" in res.attribution
    assert "Test Artist" in res.attribution
    assert "Jamendo" in res.attribution
    assert Path(res.path).is_file()


def test_jamendo_rejects_nc_falls_through_to_synth(tmp_path, monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "key123")
    _mock_jamendo(monkeypatch, _canned_tracks("http://creativecommons.org/licenses/by-nc/3.0/"))
    res = resolve("calm", cache_dir=tmp_path / "cache", duration=2.0, work_dir=tmp_path / "work")
    # NC rejected -> no jamendo track -> synth fallback
    assert res.source == "synth"
    assert res.attribution is None


def test_jamendo_rejects_nd(tmp_path, monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "key123")
    _mock_jamendo(monkeypatch, _canned_tracks("http://creativecommons.org/licenses/by-nd/3.0/"))
    res = resolve("calm", cache_dir=tmp_path / "cache", duration=2.0, work_dir=tmp_path / "work")
    assert res.source == "synth"


def test_jamendo_network_error_falls_through(tmp_path, monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "key123")

    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(bgm_library.urllib.request, "urlopen", boom)
    res = resolve("calm", cache_dir=tmp_path / "cache", duration=2.0, work_dir=tmp_path / "work")
    assert res.source == "synth"


# --- synth fallback ----------------------------------------------------------

def test_no_key_skips_online_reaches_synth(tmp_path, monkeypatch):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    # urlopen must not be invoked when there is no key
    monkeypatch.setattr(bgm_library.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network hit")))
    res = resolve("dreamy", cache_dir=tmp_path / "cache", duration=2.0, work_dir=tmp_path / "work")
    assert res.source == "synth"
    assert res.license.startswith("CC0")
    assert res.attribution is None
    assert Path(res.path).is_file()


def test_synth_is_deterministic_per_mood(tmp_path, monkeypatch):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    res1 = resolve("dreamy", cache_dir=tmp_path / "c1", duration=2.0, work_dir=tmp_path / "w1")
    res2 = resolve("dreamy", cache_dir=tmp_path / "c2", duration=2.0, work_dir=tmp_path / "w2")
    # same mood -> same synth recipe -> identical bytes
    assert Path(res1.path).read_bytes() == Path(res2.path).read_bytes()
