# Claims — Stage 6 BGM + selective subtitles

One claim per acceptance criterion in `brief.md`. Each `run-to-prove:` command
is deterministic and OFFLINE; run it from the worktree root
(`/Users/danny/Documents/PARA/Resource/autoresearch/vimax-autopilot-bgm-wt`).
Verdict starts PENDING; the verifier fills it.

---

## AC1 — Every produced video has BGM under the narration at low gain; narration stays clearly audible

**Statement:** The mix graph lays the BGM bed under the full narration at a
configurable low gain (default 0.16) and never auto-attenuates the narration
(`amix ...:normalize=0`); ducking dips the bed under the voice.

**Implements:**
- `scripts/audio_mix.py:56` `build_mix_graph` (bed at `volume=<bgm_volume>`, `normalize=0`)
- `scripts/audio_mix.py:76` narration mixed in at full level via `normalize=0`
- `scripts/audio_mix.py:101` `mix_audio` runs the graph to one AAC track
- `scripts/add_narration.py:223` `build_audio_track` wires it into Stage 6

**run-to-prove:**
```bash
python3 -m pytest tests/test_audio_mix.py -q
```
(Asserts `volume=0.16`, `normalize=0`, and the mix wiring for the default case.)

**Verdict:** PENDING

---

## AC2 — BGM is fresh per run by mood when online; offline/no-key run still produces BGM (synth pad); never hard-fails

**Statement:** `bgm_library.resolve` tries explicit > cache > Jamendo (mood
search) > synthesized CC0 pad; with no key/network it skips online cleanly and
always returns a synth pad, so the run never fails for music.

**Implements:**
- `scripts/bgm_library.py:185` `resolve` (fallback chain)
- `scripts/bgm_library.py:140` `_try_jamendo` (skips when no `JAMENDO_CLIENT_ID`; swallows errors)
- `scripts/bgm_library.py:160` `_synth_pad` (always-available ffmpeg `lavfi` pad)

**run-to-prove:**
```bash
python3 -m pytest tests/test_bgm_library.py -q
```
(Covers resolution order, no-key path reaching synth, and network-error fall-through.)

**Verdict:** PENDING

---

## AC3 — Only CC-BY/CC-BY-SA/CC0 music; attribution surfaced (CREDITS.txt + appended to upload description) when required

**Statement:** Jamendo tracks are filtered to CC-BY/CC-BY-SA/CC0 and any NC/ND
is rejected; when a track requires credit the attribution is written to
`CREDITS.txt` beside the video and threaded into the upload description.

**Implements:**
- `scripts/bgm_library.py:33-34` allowed/forbidden license regexes
- `scripts/bgm_library.py:79` `_license_ok` (rejects NC/ND)
- `scripts/add_narration.py:258` `write_credits` (CREDITS.txt beside output)
- `scripts/auto_youtube_pipeline.py:347` `_bgm_attribution` -> `--extra-description`
- `scripts/upload_youtube.py:101` `_append_extra` appends attribution to description

**run-to-prove:**
```bash
python3 -m pytest tests/test_bgm_library.py -q -k "nc or nd or attribution" && \
python3 - <<'PY'
import importlib.util, sys
def load(n,p):
    s=importlib.util.spec_from_file_location(n,p); m=importlib.util.module_from_spec(s); sys.modules[n]=m; s.loader.exec_module(m); return m
up=load("up","scripts/upload_youtube.py")
assert up._append_extra("Base", "Background music: X") == "Base\n\nBackground music: X"
assert up._append_extra("Base", "") == "Base"
pipe=load("pipe","scripts/auto_youtube_pipeline.py")
assert pipe._bgm_attribution({"bgm":{"attribution":"\"T\" by A (Jamendo, ...)"}}).startswith("Background music:")
assert pipe._bgm_attribution({"bgm":{"attribution":None}}) == ""
print("AC3 OK")
PY
```

**Verdict:** PENDING

---

## AC4 — Key sentences (from script `key_sentences`, else heuristic) appear as captions at correct times; not a full transcript

**Statement:** Only selected key indices are captioned (verbatim `key_sentences`
match, whitespace-robust; else a sparse first+every-3rd heuristic). Non-key
sentences are NOT shown.

**Implements:**
- `scripts/subtitles.py:73` `select_key_indices` (verbatim match else heuristic)
- `scripts/subtitles.py:114` `build_srt` / `scripts/subtitles.py:158` `build_ass` caption only key indices
- `scripts/add_narration.py:191` `synth_with_captions` selects + emits sidecars

**run-to-prove:**
```bash
python3 -m pytest tests/test_subtitles.py -q -k "key or srt or ass or split"
```
(Asserts only key indices captioned; heuristic fallback; verbatim whitespace robustness.)

**Verdict:** PENDING

---

## AC5 — Caption timing is exact (derived from per-sentence TTS that is the same audio muxed)

**Statement:** Each sentence is synthesized to its own WAV, each duration is
probed, offsets accumulate, and those SAME WAVs are concatenated into the
narration WAV that is muxed — so captions cannot drift.

**Implements:**
- `scripts/subtitles.py:215` `synthesize_segments` (per-sentence WAV + duration)
- `scripts/subtitles.py:56` `assemble_segments` (accumulates start/end)
- `scripts/subtitles.py:234` `concat_wavs` (same WAVs -> muxed narration)
- `scripts/add_narration.py:191` `synth_with_captions` ties timing to the muxed audio

**run-to-prove:**
```bash
python3 -m pytest tests/test_subtitles.py::test_assemble_segments_accumulates_offsets \
  tests/test_subtitles.py::test_srt_only_captions_key_indices -q && \
python3 -m pytest tests/test_add_narration_integration.py::test_subtitles_and_synth_bgm -q
```
(Integration test confirms the SRT timings come from the per-sentence durations of the muxed audio.)

**Verdict:** PENDING

---

## AC6 — Backward compatible: old script.json still runs; --no-bgm/--no-subtitles restore prior behavior

**Statement:** `read_script_fields` tolerates missing `bgm_mood`/`key_sentences`;
mood derives from youtube tags+title (else "calm ambient") and key sentences
fall back to a heuristic. `--no-bgm`/`--no-subtitles` restore the single-shot,
music-free path.

**Implements:**
- `scripts/add_narration.py:131` `read_script_fields` (tolerant of missing fields)
- `scripts/add_narration.py:166` `resolve_mood` (derivation chain)
- `scripts/add_narration.py:81,90` `--no-bgm` / `--no-subtitles` flags

**run-to-prove:**
```bash
python3 -m pytest tests/test_add_narration_integration.py::test_no_subtitles_no_bgm_keeps_audio -q && \
python3 - <<'PY'
import argparse, importlib.util, sys
s=importlib.util.spec_from_file_location("an","scripts/add_narration.py")
an=importlib.util.module_from_spec(s); sys.modules["an"]=an; s.loader.exec_module(an)
# old script.json (no bgm_mood / key_sentences) -> mood derives, no crash
fields={"narration_ko":"가.","bgm_mood":"","key_sentences":None,"youtube":{"tags":["morning","calm"],"title":"루틴"}}
ns=argparse.Namespace(bgm_mood="")
assert an.resolve_mood(ns, fields)  # non-empty derived mood
fields2={"narration_ko":"가.","bgm_mood":"","key_sentences":None,"youtube":{}}
assert an.resolve_mood(argparse.Namespace(bgm_mood=""), fields2) == "calm ambient"
print("AC6 OK")
PY
```

**Verdict:** PENDING

---

## AC7 — The full idea->private-draft flow runs from this one skill (no external repo deps)

**Statement:** The three new modules live under `scripts/` and import only the
Python stdlib + sibling modules + ffmpeg/node subprocesses; no import reaches
outside this skill.

**Implements:**
- `scripts/audio_mix.py`, `scripts/subtitles.py`, `scripts/bgm_library.py` (self-contained)
- `scripts/add_narration.py:28` `_load_sibling` imports siblings by path (cwd-independent)

**run-to-prove:**
```bash
! grep -rnE "from (tools|ViMax|google-flow-video|vimax-flow-commercial)|import (tools)\b" scripts/ && \
! grep -rn "\.\./\.\." scripts/*.py && \
for f in scripts/*.py; do python3 "$f" --help >/dev/null || { echo "FAIL $f"; exit 1; }; done && \
echo "AC7 OK: no parent-repo imports; every script parses"
```

**Verdict:** PENDING

---

## AC8 — pytest green; every scripts/*.py --help parses; offline Stage 6 yields a captioned, music-bedded MP4

**Statement:** The full suite passes, every script parses `--help`, and the
offline Stage 6 integration produces an MP4 with an audio stream + burned
captions + synth BGM.

**Implements:**
- `tests/` (57 tests) + `tests/test_add_narration_integration.py` (real ffmpeg, offline)

**run-to-prove:**
```bash
for f in scripts/*.py; do python3 "$f" --help >/dev/null || echo "FAIL $f"; done && \
python3 -m pytest tests/ -q
```
(Expect: no FAIL lines; all tests pass.)

**Verdict:** PENDING
