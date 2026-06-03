# Changelog 2026-06-03 — Per-stage verification gates ("each stage must pass")

## Why

The orchestrator chained stages on exit-code-0 + a `{"ok": true}` JSON line.
That is necessary but NOT sufficient: a stage can exit 0 and still emit a
degraded artifact, and the chain would carry it forward — even to upload.
Concretely:

- `generate_video` only checked `size > 0`; a truncated/streamless MP4 passed.
- `add_narration` emitted `"tts": true` unconditionally; a SILENT or empty
  narration WAV (TTS failure) passed silently.
- `bgm_library.resolve` always fell through to a synthesized pad, masking the
  absence of a real track.

Requirement: never continue past a failed stage (video gen, audio gen, etc.),
and make designed fallbacks opt-in rather than silent.

## What changed

- NEW `scripts/stage_gates.py`: pure ffprobe/ffmpeg verification helpers +
  per-stage gates (`gate_ideas`, `gate_storyboard`, `gate_script`, `gate_video`,
  `gate_narration`). `gate_narration` detects a silent track via
  `volumedetect` mean dBFS vs `DEFAULT_SILENCE_DB` (-50). All raise `GateError`.
- `scripts/auto_youtube_pipeline.py`: a `gate(...)` call after every stage;
  `GateError` becomes `SystemExit("GATE FAILED after '<stage>'")` so nothing
  degraded reaches the next stage or upload. Added `--allow-synth-bgm`.
- `scripts/add_narration.py`: `--allow-synth-bgm` (default off). When BGM is on
  and no REAL track resolves and synth is disallowed, it hard-stops with an
  actionable message. Self-verifies its own output with `gate_narration`.
- `scripts/bgm_library.py`: `resolve(..., allow_synth=True)` now returns `None`
  (instead of a synth pad) when `allow_synth=False` and no real source resolves.
  Default stays `True` to preserve existing offline-safe callers/tests.

## Review follow-ups applied

- Gate `add_narration` on the known output path (not `narration["out"]`) so a
  malformed stage result yields a clean GATE FAILED, not a KeyError.
- `mean_volume_db` raises on a volumedetect ffmpeg error (rc != 0) instead of
  reporting it as "silence" — avoids misdiagnosing a decode failure as TTS.
- `gate_video` distinguishes "could not read duration" from "below minimum".

## Verification

- `python3 -m pytest -q` -> 90 passed (was 68; +22 new/updated).
- `tests/test_stage_gates.py`: each gate RAISES on a degraded artifact
  (no-audio / silent / truncated / short / empty) and PASSES a real one.
- `tests/test_pipeline_gates.py`: a degraded stage output hard-stops the REAL
  `run_pipeline` BEFORE upload (junk video, silent narration).
- Live end-to-end dry validation (real codex + gen.sh image + real Supertonic
  TTS, supplied placeholder video, no Flow credits, no upload):
  all six gates passed — harvest `{count:5}`, storyboard `{frames:1}`,
  script `{narration_chars:68}`, video/delogo `{duration:2.0}`,
  narration `{duration:2.0, mean_volume_db:-23.5}`.
- Independent adversarial verifier + code-reviewer subagents both APPROVED
  (no CRITICAL/HIGH); their MEDIUM items are the follow-ups applied above.

## Note on the "5 YouTube posts" activity

Live uploads were intentionally NOT run in this change: scope was harden + commit
+ push + dry validation (no Flow credits, no real uploads). A live 5-video run
needs an attached Chrome with Flow + Studio access; with these gates, any failed
stage (video gen, audio gen, ...) now hard-stops that run instead of producing a
broken draft.
