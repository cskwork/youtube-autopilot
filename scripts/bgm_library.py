#!/usr/bin/env python3
"""Resolve ONE royalty-free background track per run, by mood, offline-safe.

Resolution order (first hit wins):
  1. explicit --bgm path (caller owns its license);
  2. local cache hit for the mood slug under cache_dir;
  3. Jamendo API IF JAMENDO_CLIENT_ID is set — CC-BY / CC-BY-SA / CC0 only,
     never NC/ND; download + cache; on ANY error fall through;
  4. synthesized ambient pad via ffmpeg lavfi (CC0, no attribution) — always
     succeeds so BGM is guaranteed even offline with no key.

Only an env key is read for Jamendo; nothing is hardcoded. The run never fails
for lack of music.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

JAMENDO_API = "https://api.jamendo.com/v3.0/tracks/"
# Accept only attribution-style or public-domain licenses; reject NC and ND.
_ALLOWED_LICENSE_RE = re.compile(r"/(by|by-sa|zero|publicdomain|cc0)(/|$)", re.IGNORECASE)
_FORBIDDEN_LICENSE_RE = re.compile(r"(by-nc|by-nd|nc-|-nc|-nd)", re.IGNORECASE)


@dataclass(frozen=True)
class BgmResult:
    """A resolved background track plus its provenance and license."""

    path: str
    source: str            # "explicit" | "cache" | "jamendo" | "synth"
    license: str
    attribution: str | None


def log(message: str) -> None:
    print(message, file=sys.stderr)


def mood_slug(mood: str) -> str:
    """Filesystem-safe slug for a mood string used as the cache key."""
    slug = re.sub(r"[^a-z0-9]+", "-", mood.strip().lower()).strip("-")
    return slug or "calm"


# --- step 1/2: explicit + cache ----------------------------------------------

def _explicit(explicit_path: str | None) -> BgmResult | None:
    if not explicit_path:
        return None
    path = Path(explicit_path).expanduser()
    if not path.is_file():
        raise SystemExit(f"--bgm file not found: {path}")
    return BgmResult(path=str(path), source="explicit", license="user-provided", attribution=None)


def _cache_hit(slug: str, cache_dir: Path) -> BgmResult | None:
    for ext in (".mp3", ".m4a", ".ogg", ".wav"):
        candidate = cache_dir / f"{slug}{ext}"
        if candidate.is_file():
            return BgmResult(path=str(candidate), source="cache",
                             license="cached (royalty-free)", attribution=None)
    return None


# --- step 3: Jamendo ---------------------------------------------------------

def _license_ok(track: dict) -> bool:
    """Accept only CC-BY / CC-BY-SA / CC0; reject any NC or ND track."""
    url = str(track.get("license_ccurl", ""))
    info = track.get("musicinfo") or {}
    blob = " ".join([url, json.dumps(info, ensure_ascii=False)])
    if _FORBIDDEN_LICENSE_RE.search(blob):
        return False
    return bool(_ALLOWED_LICENSE_RE.search(url))


def _license_label(url: str) -> str:
    low = url.lower()
    if "zero" in low or "cc0" in low or "publicdomain" in low:
        return "CC0 (Jamendo)"
    if "by-sa" in low:
        return "CC-BY-SA (Jamendo)"
    return "CC-BY (Jamendo)"


def _jamendo_query(client_id: str, mood: str, limit: int) -> str:
    params = {
        "client_id": client_id,
        "format": "json",
        "limit": str(limit),
        "fuzzytags": mood,
        "include": "licenses musicinfo",
        "audioformat": "mp32",
        "order": "popularity_total",
    }
    return JAMENDO_API + "?" + urllib.parse.urlencode(params)


def _fetch_jamendo(client_id: str, mood: str, slug: str, cache_dir: Path) -> BgmResult | None:
    """Best-effort Jamendo fetch; returns None on any error or no clean track."""
    url = _jamendo_query(client_id, mood, limit=10)
    log(f"[bgm] querying Jamendo for mood={mood!r}")
    with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    for track in payload.get("results", []):
        if not _license_ok(track):
            continue
        download = track.get("audiodownload")
        if not download:
            continue
        return _download_track(track, download, slug, cache_dir)
    return None


def _download_track(track: dict, download: str, slug: str, cache_dir: Path) -> BgmResult:
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{slug}.mp3"
    urllib.request.urlretrieve(download, str(dest))
    license_url = str(track.get("license_ccurl", ""))
    attribution = (
        f'"{track.get("name", "Untitled")}" by '
        f'{track.get("artist_name", "Unknown")} (Jamendo, {license_url})'
    )
    return BgmResult(path=str(dest), source="jamendo",
                     license=_license_label(license_url), attribution=attribution)


def _try_jamendo(mood: str, slug: str, cache_dir: Path) -> BgmResult | None:
    client_id = os.environ.get("JAMENDO_CLIENT_ID", "").strip()
    if not client_id:
        return None
    try:
        return _fetch_jamendo(client_id, mood, slug, cache_dir)
    except Exception as exc:  # network/parse/license issues -> fall through
        log(f"[bgm] Jamendo lookup failed, using synth pad: {exc}")
        return None


# --- step 4: synth pad -------------------------------------------------------

def _mood_freqs(mood: str) -> tuple[int, int, int]:
    """Derive three sine frequencies from a hash of the mood (deterministic)."""
    digest = hashlib.sha256(mood.encode("utf-8")).digest()
    base = 110 + digest[0] % 60          # ~110-170 Hz root
    return base, base * 2, int(base * 1.5)


def _synth_pad(mood: str, duration: float, work_dir: Path) -> BgmResult:
    """Build a soft ambient pad with ffmpeg lavfi: sine layers + lowpass + fades."""
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / f"pad_{mood_slug(mood)}.wav"
    f1, f2, f3 = _mood_freqs(mood)
    fade_out = max(duration - 2.0, 0.0)
    inputs: list[str] = []
    for freq in (f1, f2, f3):
        inputs += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", f"sine=frequency={freq}:sample_rate=44100"]
    fc = (
        "[0:a][1:a][2:a]amix=inputs=3:normalize=1,"
        "volume=0.5,lowpass=f=700,"
        f"afade=t=in:st=0:d=2,afade=t=out:st={fade_out:.3f}:d=2[a]"
    )
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", fc,
           "-map", "[a]", "-ar", "44100", "-ac", "2", str(out)]
    log("+ " + shlex.join(cmd))
    subprocess.run(cmd, check=True)
    if not out.exists() or out.stat().st_size == 0:
        raise SystemExit(f"synth pad produced no output at {out}")
    return BgmResult(path=str(out), source="synth", license="CC0 (synthesized)", attribution=None)


# --- public API --------------------------------------------------------------

def resolve(
    mood: str,
    *,
    explicit_path: str | None = None,
    cache_dir: Path,
    duration: float,
    work_dir: Path,
) -> BgmResult:
    """Resolve one royalty-free track for the mood via the fallback chain."""
    cache_dir = Path(cache_dir)
    work_dir = Path(work_dir)
    slug = mood_slug(mood)
    explicit = _explicit(explicit_path)
    if explicit:
        return explicit
    cached = _cache_hit(slug, cache_dir) if cache_dir.is_dir() else None
    if cached:
        return cached
    online = _try_jamendo(mood, slug, cache_dir)
    if online:
        return online
    return _synth_pad(mood, duration, work_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mood", default="calm ambient", help="mood/genre keywords")
    parser.add_argument("--bgm", help="explicit track path (highest priority)")
    parser.add_argument("--cache-dir", default="references/bgm_cache", help="track cache dir")
    parser.add_argument("--duration", type=float, default=10.0, help="synth pad length seconds")
    parser.add_argument("--work-dir", default=".", help="work dir for the synth pad")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    res = resolve(
        args.mood, explicit_path=args.bgm,
        cache_dir=Path(args.cache_dir).resolve(), duration=args.duration,
        work_dir=Path(args.work_dir).resolve(),
    )
    print(json.dumps({
        "ok": True, "path": res.path, "source": res.source,
        "license": res.license, "attribution": res.attribution,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
