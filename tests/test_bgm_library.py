"""Unit tests for BGM resolution order, license filtering, and attribution.

All network access is mocked; no real Jamendo call or download occurs.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bgm_library.py"
_SPEC = importlib.util.spec_from_file_location("bgm_library", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
bgm_library = importlib.util.module_from_spec(_SPEC)
sys.modules["bgm_library"] = bgm_library
_SPEC.loader.exec_module(bgm_library)

resolve = bgm_library.resolve


def _canned_tracks(license_url: str, download_url: str = "https://storage.jamendo.com/track.mp3"):
    """A Jamendo API response with one track at the given license + download URL."""
    return {
        "results": [
            {
                "name": "Gentle Morning",
                "artist_name": "Test Artist",
                "audiodownload": download_url,
                "license_ccurl": license_url,
                "musicinfo": {},
            }
        ]
    }


class _FakeResp(io.BytesIO):
    """A urlopen() context-manager stand-in with a .headers attribute."""

    def __init__(self, data: bytes, content_type: str):
        super().__init__(data)
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _mock_jamendo(monkeypatch, payload: dict, *, content_type="audio/mpeg", is_audio=True):
    """Patch urlopen + ffprobe so the path is fully offline.

    JSON is returned for the API query and raw bytes for the MP3 download.
    ``content_type`` lets a test simulate Jamendo's mislabeled header, and
    ``is_audio`` stubs the ffprobe-based validator (True=accept, False=reject).
    """
    def fake_urlopen(req, timeout=None):
        url = getattr(req, "full_url", req)
        if "api.jamendo.com" in str(url):
            return io.BytesIO(json.dumps(payload).encode("utf-8"))
        return _FakeResp(b"FAKEMP3DATA", content_type)

    monkeypatch.setattr(bgm_library.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(bgm_library, "_is_audio_file", lambda path: is_audio)


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


def test_download_refuses_non_jamendo_host_falls_through(tmp_path, monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "key123")
    # API returns a clean CC-BY track but with an off-host download URL.
    payload = _canned_tracks(
        "http://creativecommons.org/licenses/by/3.0/",
        download_url="https://evil.example.com/track.mp3",
    )
    _mock_jamendo(monkeypatch, payload)
    res = resolve("calm", cache_dir=tmp_path / "cache", duration=2.0, work_dir=tmp_path / "work")
    # non-jamendo host refused -> bounded download raises -> synth fallback
    assert res.source == "synth"
    assert res.attribution is None


def test_jamendo_accepts_mislabeled_html_content_type_when_audio(tmp_path, monkeypatch):
    """Jamendo mislabels real MP3s as text/html; ffprobe says audio -> accept."""
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "key123")
    _mock_jamendo(
        monkeypatch,
        _canned_tracks("http://creativecommons.org/licenses/by/3.0/"),
        content_type="text/html; charset=UTF-8",
        is_audio=True,
    )
    cache = tmp_path / "cache"
    res = resolve("calm", cache_dir=cache, duration=10.0, work_dir=tmp_path / "work")
    assert res.source == "jamendo"
    assert res.attribution is not None and "Gentle Morning" in res.attribution
    assert Path(res.path).is_file()
    assert (cache / f"{bgm_library.mood_slug('calm')}.json").is_file()


def test_jamendo_rejects_non_audio_bytes_falls_through_to_synth(tmp_path, monkeypatch):
    """ffprobe finds no audio stream -> reject the download -> synth fallback."""
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "key123")
    _mock_jamendo(
        monkeypatch,
        _canned_tracks("http://creativecommons.org/licenses/by/3.0/"),
        content_type="text/html; charset=UTF-8",
        is_audio=False,
    )
    res = resolve("calm", cache_dir=tmp_path / "cache", duration=2.0, work_dir=tmp_path / "work")
    assert res.source == "synth"
    assert res.attribution is None


# --- cache provenance sidecar ------------------------------------------------

def test_cache_sidecar_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "key123")
    cache = tmp_path / "cache"
    _mock_jamendo(monkeypatch, _canned_tracks("http://creativecommons.org/licenses/by-sa/3.0/"))
    # First resolve downloads + writes the sidecar.
    first = resolve("calm", cache_dir=cache, duration=10.0, work_dir=tmp_path / "work")
    assert first.source == "jamendo"
    slug = bgm_library.mood_slug("calm")
    sidecar = cache / f"{slug}.json"
    assert sidecar.is_file()
    # Second resolve is a cache hit and must report the REAL license/attribution.
    second = resolve("calm", cache_dir=cache, duration=10.0, work_dir=tmp_path / "work")
    assert second.source == "cache"
    assert second.license == first.license
    assert second.attribution == first.attribution
    assert "Gentle Morning" in (second.attribution or "")


def test_cache_hit_without_sidecar_uses_generic_label(tmp_path, monkeypatch):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    cache = tmp_path / "cache"
    cache.mkdir(parents=True)
    slug = bgm_library.mood_slug("calm")
    (cache / f"{slug}.mp3").write_bytes(b"handdropped")
    res = resolve("calm", cache_dir=cache, duration=10.0, work_dir=tmp_path / "work")
    assert res.source == "cache"
    assert res.license == "cached (royalty-free)"
    assert res.attribution is None


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
