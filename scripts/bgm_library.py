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
# Bound the MP3 download: only jamendo over https, audio content, capped size.
_MAX_BGM_BYTES = 30 * 1024 * 1024


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
            provenance = _read_sidecar(cache_dir / f"{slug}.json")
            return BgmResult(
                path=str(candidate),
                source="cache",
                license=str(provenance.get("license") or "cached (royalty-free)"),
                attribution=provenance.get("attribution"),
            )
    return None


def _read_sidecar(sidecar: Path) -> dict[str, str | None]:
    """Read cached track provenance; fall back to the generic label if absent."""
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"license": "cached (royalty-free)", "attribution": None}
    return {
        "license": str(data.get("license") or "cached (royalty-free)"),
        "attribution": data.get("attribution"),
    }


def _write_sidecar(sidecar: Path, source: str, license_label: str,
                   attribution: str | None) -> None:
    """Persist a cache provenance sidecar next to the downloaded audio."""
    sidecar.write_text(
        json.dumps(
            {"source": source, "license": license_label, "attribution": attribution},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


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
        "audiodownload_allowed": "true",
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


def _is_audio_file(path: Path) -> bool:
    """True if ffprobe finds a decodable audio stream in the written file.

    Content-based check: Jamendo's storage mislabels real MP3s as text/html,
    so the header is unreliable. ffprobe is authoritative. Returns False on any
    ffprobe error so a junk/HTML payload degrades to the synth pad.
    """
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "default=nw=1:nk=1",
             str(path)],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return False
    return proc.stdout.strip() == "audio"


def _bounded_download(url: str, dest: Path) -> None:
    """Fetch an MP3 with host/scheme checks, a size cap, and ffprobe validation.

    Only https jamendo.com hosts are allowed and the payload must stay under
    ``_MAX_BGM_BYTES``. Content-Type is logged but NOT gated (Jamendo mislabels
    audio as text/html); instead the written file must decode as audio per
    ``_is_audio_file``. Any violation raises so the caller's try/except degrades
    to the synth pad instead of hanging or trusting junk.
    """
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "jamendo.com" or host.endswith(".jamendo.com")):
        raise ValueError(f"refusing non-jamendo BGM url: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "vimax-bgm/1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        log(f"[bgm] downloading track (advisory content-type={ctype!r})")
        data = resp.read(_MAX_BGM_BYTES + 1)
    if len(data) > _MAX_BGM_BYTES:
        raise ValueError(f"BGM download exceeds {_MAX_BGM_BYTES} bytes")
    dest.write_bytes(data)
    if not _is_audio_file(dest):
        dest.unlink(missing_ok=True)
        raise ValueError(f"BGM download is not decodable audio: {url}")


def _download_track(track: dict, download: str, slug: str, cache_dir: Path) -> BgmResult:
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{slug}.mp3"
    _bounded_download(download, dest)
    license_url = str(track.get("license_ccurl", ""))
    license_label = _license_label(license_url)
    attribution = (
        f'"{track.get("name", "Untitled")}" by '
        f'{track.get("artist_name", "Unknown")} (Jamendo, {license_url})'
    )
    _write_sidecar(cache_dir / f"{slug}.json", "jamendo", license_label, attribution)
    return BgmResult(path=str(dest), source="jamendo",
                     license=license_label, attribution=attribution)


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
    allow_synth: bool = True,
) -> BgmResult | None:
    """Resolve one royalty-free track for the mood via the fallback chain.

    Order: explicit > cache > Jamendo > synthesized pad. When ``allow_synth`` is
    False, the synthesized-pad fallback is skipped and ``None`` is returned if no
    REAL source (explicit/cache/Jamendo) resolves, so the caller can hard-stop
    instead of silently degrading to synth. ``allow_synth`` defaults True to keep
    the offline-safe guarantee for callers that opt into it.
    """
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
    if not allow_synth:
        return None
    return _synth_pad(mood, duration, work_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mood", default="calm ambient", help="mood/genre keywords")
    parser.add_argument("--bgm", help="explicit track path (highest priority)")
    parser.add_argument("--cache-dir", default="references/bgm_cache", help="track cache dir")
    parser.add_argument("--duration", type=float, default=10.0, help="synth pad length seconds")
    parser.add_argument("--work-dir", default=".", help="work dir for the synth pad")
    parser.add_argument("--no-synth", dest="allow_synth", action="store_false",
                        help="do not fall back to the synthesized pad; fail if no real track resolves")
    parser.set_defaults(allow_synth=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    res = resolve(
        args.mood, explicit_path=args.bgm,
        cache_dir=Path(args.cache_dir).resolve(), duration=args.duration,
        work_dir=Path(args.work_dir).resolve(), allow_synth=args.allow_synth,
    )
    if res is None:
        raise SystemExit(
            f"no real BGM resolved for mood={args.mood!r} and --no-synth set "
            "(provide --bgm, a cache hit, or JAMENDO_CLIENT_ID)"
        )
    print(json.dumps({
        "ok": True, "path": res.path, "source": res.source,
        "license": res.license, "attribution": res.attribution,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
