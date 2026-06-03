# Run: BGM + selective subtitles for vimax-youtube-autopilot

- **Mode**: LEGACY (add feature to existing self-contained skill repo)
- **Date**: 2026-06-03
- **base_branch**: `main` (autopilot nested repo @ `b187a8e`)
- **run_branch / target_branch**: `feat/bgm-subtitles` (feature branch; NOT auto-merged to main)
- **worktree_path**: `/Users/danny/Documents/PARA/Resource/autoresearch/vimax-autopilot-bgm-wt`
- **Repo under change**: `skills/vimax-youtube-autopilot/` (its OWN git repo, nested inside ViMax; ViMax treats it as untracked)

## Objective

Stage 6 (`add_narration.py`) currently does Korean TTS + a plain ffmpeg mux. Add:
1. Always lay a **royalty-free background music** track under the TTS narration at **low volume**, looped/trimmed + faded to the narration length.
2. Each run, **search an appropriate (mood-matched) free track** online; robust offline fallback so BGM is *always* present.
3. Burn **selective subtitles** for **key sentences only** ("부분부분"), with exact timing from sentence-level TTS.

## Hard constraints (from user)

- **Self-contained**: the entire flow (idea -> video -> BGM -> subtitles -> private YouTube draft) must run from **this one skill** alone. No reaching into the parent ViMax repo's `tools/` or other skills.
- BGM volume small; narration must stay clearly audible.
- Subtitles only for key parts, not a full transcript wall.
- Free / royalty-free music only; attribution surfaced when the license requires it.

## Priority Rules (domain: media pipeline / ffmpeg / a11y)

1. Narration intelligibility is paramount — BGM never masks speech (low gain, optional sidechain ducking).
2. BGM always present (always-on requirement) — degrade gracefully through a fallback chain, never hard-fail the run.
3. Audio/subtitle timing must be exact — captions derive from the same per-sentence audio that is muxed (no drift).
4. License-clean by construction — only CC-BY / CC-BY-SA / CC0; never NC/ND; carry attribution to the description.
5. Backward compatible — old `script.json` (no new fields) still runs; new fields are optional with safe derivation.
6. Cohesive small modules — one file per concern (library / mix / subtitles); functions <=50 lines.
7. Offline-testable — every gate-relevant path is verifiable without network or a music API key.
8. No secrets hardcoded — music API key via env var only; absent key falls back, does not crash.
9. Surgical — touch only Stage 6 + the script schema + docs; do not redesign other stages.
10. Honest gates — tests prove behavior; delivery gate is literal and never edited to pass.

See `plan.md` for the frozen design and both briefs. `state.json` tracks phase status.
