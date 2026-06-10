# 2026-06-10 — url-ad: commercial-grade ad creative system

Goal: make url-ad function as a high-quality, trend-aware commercial/Shorts ad
maker (entertaining full captions, professional structure, lively pacing),
borrowing proven patterns from the superdesign and supergoal skills.

## Decisions and reasoning

- **Creative direction as a routed step, not a template** (`references/ad-creative.md`):
  superdesign's loop (brief read -> dated trend pulse -> direction routing ->
  dials -> deterministic gate -> independent critic) maps cleanly onto ad
  making. One ad style family is chosen per run (problem-solution /
  demo-forward / listicle / before-after / question-hook) instead of one house
  style, and reaches codex via the new `--style-direction` flag
  (write_script.py `_direction_block`). Trend pulse uses live search when
  available; otherwise a DATED baked snapshot (recorded 2026-06-10, knowledge
  through 2026-01) is used and disclosed — never silently faked.
- **Deterministic quality floor** (`stage_gates.gate_ad_quality`): supergoal's
  "verify vs ground truth, writer never self-approves" principle. Machine-
  checkable proxies for the evidence-backed TikTok/Shorts rules already cited
  in url-ad.md: opening sentence within a ~3.5s speech window (hook), total
  narration in a 12-60s budget, key_sentences verbatim (else caption slots
  never fire), closing CTA in key_sentences (CTA burns on screen). Wired into
  `run_pipeline_urlad` right after `gate_script`, so a weak script hard-stops
  before any render spend. Speech time estimated at 5.5 chars/s (same constant
  the orchestrator already uses) — no TTS run inside the gate.
- **Full-coverage, brand-accented captions for ads**: sound-off feeds make
  every-sentence captions table stakes for ad shorts. `subtitles.select_key_indices`
  gains `coverage="all"`; `build_ass` gains `brand_colors` (hex -> ASS accent,
  skipping colors below a 0.25 relative-luminance floor for legibility).
  `add_narration.py` exposes `--caption-coverage` / `--brand-colors`; the
  orchestrator auto-wires both for url-ad from `page_facts.brand_colors`
  (`_urlad_caption_args`). idea-video keeps the selective variety look —
  defaults unchanged.

## Live run + feedback loop (eng-stt-module.vercel.app/learning-web)

First real url-ad production exercised the full creative loop end to end:

1. Ingest (launch mode, no attach): 8 vertical screenshots + codex-distilled
   page_facts (4 value props, gate_page_facts OK). brand_colors enriched by
   MEASURING the capture pixels (#2D55D8/#5B7BE1 icon royal blue) — grounded,
   not invented.
2. Brief read + routing: student-facing AI English learning app; 4 equal value
   props -> listicle family, lively, full captions, 해요체. Trend pulse used the
   dated 2026-06-10 snapshot (live web search unavailable in this harness;
   disclosed per ad-creative.md).
3. Attempt 1: gate_ad_quality HARD-STOPPED a buried hook (~5.3s opening
   sentence) before any render — the gate worked as designed. Gate message
   folded into --style-direction (explicit 18-char opening budget).
4. Attempt 2: script passed hook (2.18s) but exposed a real harness gap —
   codex trims lead-in ordinals from key_sentences, and exact-equality
   matching rejected it. Root-cause fix in code (containment matching in
   subtitles._match_verbatim AND gate_ad_quality, TDD; 143 passed), then the
   attempt-2 script passed without re-spending codex tokens.
5. Render: Ken-Burns slideshow (29.8s, gate_video OK) -> Supertonic Mina TTS
   x10 sentences + fresh Jamendo CC-BY BGM (ducked, CREDITS.txt) ->
   full-coverage brand-accented burned captions -> narrated.mp4 1080x1920
   h264+aac 26.3s, gate_narration OK (mean -25.8 dB). Frame inspection
   confirmed faithful page pixels + bold black-box captions with royal-blue
   keyword pops.

Logged follow-up in references/improvement_log.md: crop shots to the content
bounding box for short single-page sites (empty background below content).

## v2 — user feedback loop ("시각적 포커스 안 맞음, dynamic 없음")

The v1 ad showed the full short menu page (content in the top quarter, empty
cream below) and never matched visuals to narration beats. Three fixes:

1. Interactive capture (one-off run-code scripts via the playwright CLI,
   launch mode): click into each menu card and one level deeper — AI Talking
   topic -> speaking exercise ("I brush my teeth." + 듣기/녹음), Role-play role
   pick -> cafe conversation, Writing form with a typed sample draft, chatbot
   live English message. Real product UI instead of five copies of the menu.
2. Scene-per-sentence assembly: each of the 10 narration sentences got its own
   content-cropped shot rendered as a Ken-Burns clip with that sentence's
   exact duration (from captions.srt), alternating pan direction, then
   concatenated. Narration and visuals are now in sync; a cut lands every
   ~2.5s.
3. `build_kenburns_clip.build_filter` gained an auto fit axis (`src_aspect`,
   TDD in tests/test_kenburns.py): wide content crops fit by width — the old
   height-only fit blew a 720x330 crop past the 9:16 frame.

Output `out/engstt-ad/narrated_v2.mp4` (26.3s), gate_video + gate_narration
OK, frame QA confirmed sentence-screen sync (exercise card under "그림 보고
따라 말해요", cafe dialog under "상황 속 영어가 쉬워져요", menu CTA under the
closing line). 146 tests pass.

## Verified

- TDD: new tests written RED first, then implementation GREEN.
- `python3 -m pytest -q` -> 141 passed (gates RED/GREEN incl. 6 new
  gate_ad_quality cases, 4 caption-mode cases, 2 style-direction cases,
  4 url-ad wiring cases incl. the ad_quality hard-stop before visuals).
- `--help` parses for all touched CLIs (add_narration, write_script,
  auto_youtube_pipeline, subtitles).
