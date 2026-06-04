# Verification — Stage 6 BGM + selective subtitles

- **Verifier**: adversarial, separate pass (did not write the code).
- **Build commit (first verify)**: `ee5ceab`. **Final commit (delivered)**: `a1ddb8e` (after review-fix cycle 1 + micro-fix). See the "Final state" section at the bottom — it supersedes the counts below.
- **Verify worktree** (clean checkout): `youtube-autopilot-verify-wt`.
- **Toolchain**: Python 3.12.7, pytest, ffmpeg/ffprobe 7.1.1. All checks run FROM the verify worktree, offline, `JAMENDO_CLIENT_ID` unset unless a test sets it.

> The per-claim table below is the first-pass record at `ee5ceab` (57 tests). It remained GREEN. The fix cycle then CLOSED several "Not covered" gaps and added tests (57 -> 68). Authoritative final evidence is in **## Final state @ a1ddb8e**.

---

## Per-claim results (re-run from the verify worktree)

| Claim | Verdict | Evidence (command + key output) |
|---|---|---|
| **AC1** narration audible / low BGM + ducking | **GREEN** | `pytest tests/test_audio_mix.py -q` -> `9 passed`. Adversarial: ran `mix_audio(duck=True)`; graph = `[1:a]volume=0.16,afade…[bg];[bg][0:a]sidechaincompress=…[bgd];[0:a][bgd]amix=inputs=2:duration=first:normalize=0[mix]`. ffmpeg ACCEPTS the reused `[0:a]` pad (narration = both sidechain key and mix input). Isolated sidechain test: bed **-31.7 dB while voice present vs -24.1 dB while silent = 7.6 dB dip** -> BGM is ducked, NOT the narration. `amix duration=first` trims a 2 s looped bed to the 5 s narration (output dur=5.0). `afade out st=4.0 = dur(5)-fade(1)`. |
| **AC2** fresh-by-mood online / always-on synth fallback; never hard-fails | **GREEN** | `pytest tests/test_bgm_library.py -q` -> `8 passed`. Adversarial (no key, no cache, no `--bgm`): normal/empty/garbage-non-ASCII moods AND a 0.5 s edge duration ALL reach `source=synth`, a real playable stereo 44.1 kHz WAV (ffprobe confirmed), no branch raised. |
| **AC3** license-clean + attribution | **GREEN** | `pytest tests/test_bgm_library.py -k "nc or nd or attribution"` -> `4 passed`; inline `_append_extra`/`_bgm_attribution` -> `AC3 OK`. Adversarial: mocked payload with by-nc, by-nd, **and** by-nc-sa listed BEFORE a clean CC-BY -> resolver downloads ONLY `ok.mp3` (the CC-BY), attribution = `"Clean CCBY" by GoodArtist (Jamendo, …/by/4.0/)`. `_license_ok` matrix exhaustively correct (by, by-sa, cc0 accept; nc, nd, nc-sa, nc-nd reject). Key is env-only; `grep` found NO hardcoded id/secret. |
| **AC4** selective captions, not full transcript | **GREEN** | `pytest tests/test_subtitles.py -k "key or srt or ass or split"` -> `12 passed`. Adversarial: 30-sentence narration, no keys -> heuristic captions only `[0,3,6,9,12,15,18,21]` (cap 8), `[0,3,6,9,12]` (cap 5), `[0,3,6]` (cap 3); never all 30. Explicit keys map to exact indices. |
| **AC5** caption timing exact (same audio muxed) | **GREEN** | `pytest …test_assemble_segments_accumulates_offsets …test_srt_only_captions_key_indices` -> `2 passed`; `…test_subtitles_and_synth_bgm` -> `1 passed`. Adversarial: stub TTS with **distinct per-sentence durations** (0.5/2.1/1.5/0.5 s). Key sentence at index 2 got SRT start **2.6 s = exactly d0+d1 (0.5+2.1)**, end 4.1 = +1.5. Timing derives from probing the per-sentence WAVs that are concatenated into the muxed narration — not estimated. |
| **AC6** backward compatible / `--no-bgm`/`--no-subtitles` | **GREEN** | `…test_no_subtitles_no_bgm_keeps_audio` -> `1 passed`; inline mood derivation -> `AC6 OK`. Adversarial end-to-end on an OLD-style `script.json` (only `narration_ko`+`youtube`, no `bgm_mood`/`key_sentences`): defaults run -> `bgm.source=synth`, `key_count=2` (heuristic), no crash; `--no-bgm --no-subtitles` -> `bgm=None subtitles=None tts=True`, output still has an audio stream. `write_script.py --help` and `upload_youtube.py --help` parse (validate change does not crash on `--help`). |
| **AC7** self-contained (no external repo deps) | **GREEN** (with note) | claim grep passes -> `AC7 OK`. Broad sweep: the 3 new modules + `add_narration.py` import only stdlib + sibling-by-path (`_load_sibling`). No `import`/`from` reaches the parent parent-repo `tools/`, other skills, or `../..`. NOTE: `auto_youtube_pipeline.py:36 DEFAULT_OUT_DIR` is a hardcoded absolute path into `parent-repo/.working_dir/…` — but it is a runtime OUTPUT-dir default (a `--out-dir` default), NOT a source/import dependency, and it is **pre-existing on main** (not in this diff). Out-of-scope portability wart, not an AC7 violation. |
| **AC8** pytest green / all `--help` parse / offline captioned music-bedded MP4 | **GREEN** | `for f in scripts/*.py; do … --help; done` -> all 16 `ok`, no FAIL. `pytest tests/ -q` -> **57 passed in 2.83 s**. Adversarial: subtitles-on mux runs `-vf ass=… -c:v libx264 -crf 18` (burn re-encode), output video codec = h264, only the key sentence in the ASS dialogue. Synth BGM bedded, captions burned, offline. |

**Aggregate: every claim re-verified GREEN.**

---

## Coverage (AC1..AC8 -> domain checklist)

| AC | Brief criterion | Status | Domain checklist item proven |
|---|---|---|---|
| AC1 | BGM under narration at low gain; narration audible | **GREEN** | audio intelligibility — `normalize=0` (narration full), `volume=0.16` bed, sidechain ducks the BED 7.6 dB (not the voice), `duration=first` trims bed to narration, fade-out at `dur-fade` |
| AC2 | fresh-by-mood online; offline/no-key still produces BGM; never hard-fails | **GREEN** | always-on fallback — synth pad reached for any mood incl. empty/garbage and 0.5 s edge; real playable file; no raise |
| AC3 | only CC-BY/CC-BY-SA/CC0; attribution -> CREDITS + description | **GREEN** | license + secrets — NC/ND/NC-SA rejected even when listed first; CC-BY chosen; attribution well-formed; key env-only; no hardcoded secret |
| AC4 | key sentences captioned, not full transcript | **GREEN** | selective captions — sparse heuristic capped; explicit keys -> exact indices; 30-sentence narration never fully captioned |
| AC5 | caption timing exact from the same muxed per-sentence TTS | **GREEN** | timing exactness — caption start == accumulated probed per-sentence WAV durations; same WAVs concatenated into muxed narration |
| AC6 | old script.json runs; `--no-bgm`/`--no-subtitles` restore prior | **GREEN** | backward-compat — old script E2E (mood derived, heuristic captions); flags restore single-shot music-free path; `--help` safe |
| AC7 | full flow from one skill, no external repo deps | **GREEN** (note) | self-contained — new modules import only stdlib + siblings; pre-existing hardcoded OUTPUT dir is a runtime default, not a source dep |
| AC8 | pytest green; every `--help` parses; offline captioned music-bedded MP4 | **GREEN** | 57 passed; 16/16 `--help` ok; offline burn re-encode + synth bed produces the MP4 |

### Static-analysis findings (real bug vs noise)
- **`add_narration.py:290` `burn_ass = captions["ass"]` typed `object` -> `mux_final(burn_ass: str|None)`**: **NOT a real bug — typing annotation gap only.** Only two assignments to `burn_ass` exist: `None` (subtitles off -> `-c:v copy`, `burn_vf` never called) and `captions["ass"]`, where `write_captions` ALWAYS sets `"ass": str(ass)` (a real `str`). The widening is purely from `dict[str, object]`. Runtime path proven: subtitles-on integration re-encodes with `-vf ass=` and produces h264. No path passes a non-str/non-None to ffmpeg `-vf`.
- **`upload_youtube.py:152-155` google-auth type errors**: **PRE-EXISTING on `main`, out-of-scope.** `git diff main..HEAD -- scripts/upload_youtube.py` is `+12 lines only` (the `--extra-description` arg, `_append_extra` helper, one call in `resolve_metadata`). The credentials region (`_refresh_or_consent`, `InstalledAppFlow.from_client_secrets_file`, `flow.run_local_server`, `_persist_token`) is untouched by this build. The errors are google-auth library stub typing, not introduced here.

**Not covered:** live Jamendo reachability + a real CC-BY download (online path is structurally proven via mocked HTTP only); perceptual loudness / true intelligibility of voice-over-music (only relative dB-dip and graph structure proven, not a listening test); a real YouTube upload (uploader exercised only via `--help` + `_append_extra`/`_bgm_attribution` inline asserts — no test runs `upload_youtube.py` end-to-end, dry-run included); Supertonic real-model prosody/latency (stubbed); the orchestrator `auto_youtube_pipeline.py` is NOT exercised by any test (no offline orchestrator dry-run test — Stage 6 integration is tested in isolation, not via the conductor); `write_script.py validate()` has NO unit test (only `--help` parse); `--keep-original-audio` mix path exercised only in my ad-hoc probe, not a committed test.

**Regression tests:** `tests/test_remove_logo.py` -> **25 passed** (green). Full suite **57 passed** (2 integration + 9 audio_mix + 8 bgm_library + 25 remove_logo + 13 subtitles). No pre-existing test regressed.

---

verdict: GREEN (first pass @ ee5ceab)

Every claim AC1..AC8 re-verified GREEN from the clean verify worktree with fresh evidence and independent adversarial probes; no real bug found (the two static findings are a typing gap and a pre-existing out-of-scope library issue). Residual items are test-coverage gaps — recorded under "Not covered" rather than as blockers.

---

## Final state @ a1ddb8e (review-fix cycle 1 + micro-fix + delivery gate)

After the first GREEN, three expert reviews (architect / security / code-reviewer) APPROVED with no CRITICAL/HIGH, and QA PASSED (full 7-stage orchestrator ran end-to-end OFFLINE producing a captioned, synth-BGM MP4). Convergent MEDIUM/LOW findings were fixed:

- **F1** manifest `wav` parity — `add_narration.py:303` emits `"wav": str(narration)` (closes the silent manifest regression vs main).
- **F2** explicit duck graph — `audio_mix.py:78` `[0:a]asplit=2[nar0][nar1]`; `[nar0]` = sidechain key, `[nar1]` = final amix. Portable on stock ffmpeg; behavior identical (BGM ducks, narration full, `normalize=0`, `duration=first`).
- **F3** bounded Jamendo download — https + `*.jamendo.com` host guard, 15 s timeout, content-type check, 30 MB cap; any violation degrades to the synth pad.
- **F4 + micro-fix** cache provenance sidecar — `<slug>.json` carries real source/license/attribution; cache hit reports them; missing/empty license falls back to a non-None `"cached (royalty-free)"` (no `license=None`).
- **F5** lint — removed unused `import shutil`/`import pytest`; `burn_ass` now `str | None`.
- **F6** tests — added a LEGACY-`script.json` integration case (closes the AC6 *test* gap + exercises `resolve_mood` derivation) and `tests/test_write_script.py` for `validate()` (closes that gap).
- **F7** doc — SKILL.md now says `-stream_loop -1` + `amix duration=first` (was `aloop`).

### Delivery gate (literal, run from the clean verify worktree @ a1ddb8e)
- `for f in scripts/*.py; do python3 "$f" --help; done` -> **16/16 ok**, no FAIL.
- `pytest tests/ -q` -> **68 passed** (was 57; +11).
- Regression `pytest tests/test_remove_logo.py -q` -> **25 passed**.
- AC7 self-contained sweep (`grep` for parent-repo/other-skill imports in `scripts/`) -> **none** -> OK.
- `python3 -m py_compile scripts/*.py` -> OK. No new real type/lint error remains (the sole new one from F4 was fixed by the micro-fix; `upload_youtube.py` google-auth stub noise is pre-existing on main).
- Key fixes confirmed present by grep: F1 `"wav"`, F2 `asplit=2[nar0][nar1]`, F3 jamendo host guard, F5 imports removed, F7 `-stream_loop`.

### Coverage delta (gaps CLOSED by the fix cycle)
- Orchestrator end-to-end OFFLINE: **CLOSED** by QA (real `auto_youtube_pipeline.py`, 7 stages, stubbed codex+supertts, synth BGM, dry-run upload -> `narrated.mp4` h264+aac + selective `.srt` (3/6 key sentences) + manifest `bgm.source=synth`). Evidence in `qa.md`.
- `write_script.validate()` unit test: **CLOSED** (`tests/test_write_script.py`).
- Backward-compat (old script.json) committed test: **CLOSED** (legacy case in `tests/test_add_narration_integration.py`).

**Not covered (residual, non-blocking):** live Jamendo reachability + a real CC-BY download (mock-only); perceptual loudness / true voice-over-music intelligibility (only relative dB-dip + graph structure proven); a real YouTube upload (uploaders exercised via `--help` + inline asserts + QA dry-run, not a live publish); Supertonic real-model prosody/latency (stubbed); `--keep-original-audio` mix path (ad-hoc probe only, no committed test).

**Regression tests:** `tests/test_remove_logo.py` -> 25 passed. Full suite -> 68 passed (2->3 integration + 9 audio_mix + bgm_library + 25 remove_logo + subtitles + new write_script). No pre-existing test regressed.

verdict: GREEN (final @ a1ddb8e)

All AC1..AC8 GREEN; expert panel APPROVED; QA PASS; delivery gate exit-0 with 68/68 tests. No CRITICAL/HIGH and no real defect outstanding. Residual items are explicit out-of-scope coverage gaps (live network, perceptual, real upload), recorded above — not behavior defects.
