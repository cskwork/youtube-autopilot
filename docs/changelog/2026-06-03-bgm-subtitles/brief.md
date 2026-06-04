# Brief

- **Mode**: LEGACY (no Validate/GO gate). Decision to proceed: pending Human Feedback.
- **Goal**: Add always-on low-volume royalty-free BGM + selective key-sentence subtitles to Stage 6 of youtube-autopilot, fully self-contained in the skill.
- **Acceptance criteria** (carried into the Verify Coverage map):
  1. Every produced video has BGM under the narration at low gain; narration stays clearly audible.
  2. BGM is selected fresh per run by mood when online; an offline/no-key run still produces BGM (synth pad). Run never hard-fails for music.
  3. Only CC-BY/CC-BY-SA/CC0 music; attribution surfaced (CREDITS.txt + appended to upload description) when required.
  4. Key sentences (from script `key_sentences`, else heuristic) appear as on-screen captions at correct times; not a full transcript.
  5. Caption timing is exact (derived from per-sentence TTS that is the same audio muxed).
  6. Backward compatible: old `script.json` still runs; `--no-bgm`/`--no-subtitles` restore prior behavior.
  7. The full "idea -> private draft" flow runs from this one skill (no external repo deps); one-command orchestrator unchanged in spirit.
  8. `pytest tests/ -q` green; every `scripts/*.py --help` parses; offline orchestrator dry-run yields a captioned, music-bedded MP4.

Decision: GO (user approved 2026-06-03). Calibration: BGM low-volume + sidechain ducking ON; attribution auto-appended to upload description + CREDITS.txt.
