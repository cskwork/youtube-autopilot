# Plan (FROZEN) — BGM + selective subtitles for Stage 6

> Frozen at Human Feedback. Build implements this; it does not redesign.

---

## A. Plain-language brief (for anyone)

Right now the autopilot makes a video and reads a Korean script over it with a
computer voice. Two things are missing that this change adds:

1. **Background music.** Every video will now have soft music playing under the
   narration — quiet enough that the voice is always clear. Each run the pipeline
   picks a *fresh, mood-appropriate, free* track (so it is not the same song every
   time). If the internet or the music service is unavailable, it still lays down
   a gentle built-in ambient pad so there is *always* music, and the run never
   breaks. Only royalty-free music is used, and when a track requires credit, the
   credit line is added to the YouTube description automatically.

2. **Key-moment subtitles.** Instead of subtitling every word, only the
   **important sentences** appear as on-screen captions, at the exact moment they
   are spoken. We get exact timing by voicing the script one sentence at a time
   and measuring each, so captions never drift out of sync.

Everything stays inside the one `youtube-autopilot` skill — you can still
run the whole "idea -> private YouTube draft" flow with a single command, now
with music and captions baked in.

---

## B. Technical brief (for a novice developer)

### Where it plugs in
Stage 6 = `scripts/add_narration.py` (TTS + ffmpeg mux). That is the only stage
that changes behaviorally. We split the new work into three small, cohesive
modules (one concern each), all under `scripts/` so the skill stays
self-contained:

| New module | Responsibility |
|---|---|
| `scripts/subtitles.py` | Korean sentence segmentation; per-sentence Supertonic TTS -> exact durations; concat into one narration WAV; pick key sentences; emit `.srt` + `.ass`; provide the burn-in video filter. |
| `scripts/bgm_library.py` | Resolve ONE royalty-free track per run by mood, with a fallback chain; return path + license/attribution. |
| `scripts/audio_mix.py` | Pure ffmpeg-filter-graph builder: narration (full) + optional original audio + BGM (low gain, `aloop`+trim, `afade` in/out, optional `sidechaincompress` ducking) -> one mixed AAC. |

`add_narration.py` becomes the Stage 6 conductor that calls these three, then does
the final mux (video + mixed audio + burned key-sentence subtitles).

### Audio/timing model (no drift)
1. Split `narration_ko` into sentences (deterministic Korean-aware splitter).
2. Synthesize **each sentence** with Supertonic into its own WAV; `ffprobe` its
   duration; accumulate start/end offsets.
3. `concat` the per-sentence WAVs into the full narration WAV — the SAME audio the
   timings describe, so captions are frame-accurate.
4. `audio_mix.py` lays BGM under that narration WAV at low gain.
5. Final ffmpeg burns ONLY the key sentences (`ass=` filter, re-encode video).

> Supertonic is invoked per sentence. `npm exec --yes` caches the package after
> the first call, so subsequent sentences are fast. If `supertts` is on PATH it is
> used directly. A `--subtitles/--no-subtitles` flag keeps the old single-shot
> whole-text path available (back-compat / speed).

### BGM resolution order (always-on, license-clean, offline-safe)
`bgm_library.resolve(mood, explicit, cache_dir)` returns `(path, attribution|None)`:
1. **`--bgm <file>`** explicit override -> use it (attribution = user's concern).
2. **Local cache hit** for the mood under `references/bgm_cache/` -> reuse.
3. **Online search** *(best-effort)*: if `JAMENDO_CLIENT_ID` env is set, query the
   Jamendo API (`/v3.0/tracks` with `fuzzytags=<mood>`, license filtered to
   **CC-BY / CC-BY-SA / CC0 only** — never NC/ND), download the MP3, cache it,
   return its attribution (title/artist/license/url).
4. **Synthesized ambient pad** *(guaranteed, offline, CC0/self-made)*: build a soft
   mood-varied pad with ffmpeg `lavfi` (sine layers + lowpass + long fades) so BGM
   is ALWAYS present even with no network and no key. No attribution needed.

Key is env-only (`JAMENDO_CLIENT_ID`); absent key simply skips step 3. Nothing is
hardcoded; the run never fails for lack of music.

### Mood + key-sentence sourcing (with safe derivation)
Extend `write_script.py` `OUTPUT_SCHEMA` with two fields and update its prompt +
`validate()`:
- `bgm_mood`: short English mood/genre keywords for the music search
  (e.g., `"calm uplifting ambient corporate"`).
- `key_sentences`: array of a FEW verbatim sentences copied from `narration_ko`
  that deserve on-screen captions.

Consumers degrade gracefully if absent (old `script.json`):
- mood -> derive from `youtube.tags` + `title`, else default `"calm ambient"`.
- key sentences -> heuristic: caption a sparse subset (first sentence + roughly
  every 3rd) so captions still appear "부분부분".

### Subtitle style
Burned-in (hardsub) so they always show: bottom-centered, readable sans, white
text + semi-transparent box, safe margins. Also emit a `.srt` sidecar (cheap,
useful for manual YouTube caption upload). Hardsub forces a video re-encode
(libx264 crf 18) — acceptable; delogo/assemble already re-encode.

### Attribution thread (license compliance)
`add_narration.py` JSON result gains `bgm: {path, source, license, attribution}`.
When attribution is required, it is (a) written to a `CREDITS.txt` beside the
video, and (b) appended to the upload description: orchestrator passes
`--extra-description` (new optional flag on the uploaders) OR merges it into the
description before upload. Synth-pad fallback needs no attribution.

### New / changed CLI flags on `add_narration.py`
`--bgm <path>`, `--bgm-mood <str>`, `--bgm-volume <float>` (default ~0.16),
`--no-bgm`, `--duck/--no-duck` (sidechain ducking, default on),
`--subtitles/--no-subtitles` (default on), `--max-caption-chars`.

### Orchestrator (`auto_youtube_pipeline.py`)
`stage_narration` enables BGM + subtitles by default (reads `bgm_mood` /
`key_sentences` straight from `script.json`); add pass-through `--no-bgm` /
`--no-subtitles` / `--bgm` flags and thread BGM attribution into the manifest +
upload description. Minimal change; defaults make it "just work".

---

## C. Files changed / added

**Added** (all in `scripts/`, self-contained):
- `scripts/subtitles.py`
- `scripts/bgm_library.py`
- `scripts/audio_mix.py`
- `tests/test_subtitles.py`
- `tests/test_audio_mix.py`
- `tests/test_bgm_library.py`
- `tests/test_add_narration_integration.py` (offline, stubs Supertonic, real ffmpeg)

**Changed**:
- `scripts/add_narration.py` — call the 3 modules; final mux with mixed audio + burned subs; new flags; richer JSON result.
- `scripts/write_script.py` — schema + prompt + validate add `bgm_mood`, `key_sentences`.
- `scripts/auto_youtube_pipeline.py` — Stage 6 defaults on; attribution -> manifest + description; pass-through flags.
- `scripts/upload_youtube.py` and `scripts/upload_youtube_studio.py` — optional `--extra-description` append (attribution).
- `SKILL.md`, `README.md`, `requirements.txt` (no new pip dep expected; document ffmpeg/libass + optional `JAMENDO_CLIENT_ID`).
- `references/runbook.md` / `references/improvement_log.md` — Stage 6 BGM/subtitle notes.

---

## D. Tests (TDD; offline, gate-relevant)

- `test_audio_mix.py` — filter-graph builder string assertions: narration-only+BGM; narration+original+BGM; ducking on/off; volume param; `aloop`/trim/`afade` present; map labels correct.
- `test_subtitles.py` — Korean sentence split; SRT/ASS timing assembled from injected durations; key-sentence selection from `script.json`; heuristic fallback when absent; verbatim matching is robust to whitespace.
- `test_bgm_library.py` — resolution order (explicit > cache > Jamendo(mocked HTTP) > synth); license filter rejects NC/ND; attribution formatting; no-key path skips online cleanly.
- `test_add_narration_integration.py` — generate a 2s `lavfi` placeholder video + stub `supertts` (writes a short sine WAV per sentence); run `add_narration.py --subtitles`; assert output MP4 has an audio stream, duration > 0, and (subtitles enabled) video was re-encoded. Real ffmpeg, no network.
- `tests/test_remove_logo.py` — must still pass.

Gate: `for f in scripts/*.py; do python3 "$f" --help >/dev/null; done` clean;
`python3 -m pytest tests/ -q` green; offline dry-run of the orchestrator yields an
MP4 with audible (low) BGM + burned key captions.

---

## E. Risks & mitigations

- **Per-sentence TTS latency / prosody seams** — accept; npm cache warms after #1; `--no-subtitles` keeps the fast single-shot path.
- **Jamendo reachability / key absence** — synth-pad fallback guarantees BGM; online path is best-effort + unit-tested via mock.
- **License correctness** — hard filter to CC-BY/CC-BY-SA/CC0, attribution carried to description; synth pad is self-made CC0.
- **Hardsub re-encode cost** — bounded; matches existing re-encode stages.
- **Korean sentence splitting edge cases** — deterministic splitter + tests; captions are selective so minor mis-splits are low-impact.
- **Back-compat** — new schema fields optional with derivation; `--no-bgm/--no-subtitles` restore prior behavior.

---

## F. Out of scope

- Word-level karaoke captions; Whisper STT path; multi-track music beds; per-scene
  music changes; auto-publish. (Captions are sentence-level + selective by design.)
