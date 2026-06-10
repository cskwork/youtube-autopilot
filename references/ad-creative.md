# Ad creative direction (url-ad)

Creative system for the url-ad workflow, run BETWEEN ingest (Stage 0) and
script (Stage 1). Pattern borrowed from the superdesign skill: read the brief,
pulse current trends (dated; snapshot fallback), route to ONE direction that
fits, declare the dials, then let a deterministic gate + an independent critic
verify — the writer never self-approves.

## A. Brief read (one line, stated to the user)

From `page_facts.json`, state in ONE line: product category, likely audience,
brand vibe (from title/value_props wording + brand_colors), and what the ad
must make the viewer DO (`cta_text`). Design the ad to this brief, never to a
default template.

## B. Trend pulse (dated)

Try a live web search for "short-form video ad trends <year>" + the product
category; record the read with a date. Reuse a read up to 30 days old. If
search is unavailable, use the snapshot below and DISCLOSE that in the run log.

Snapshot (recorded 2026-06-10 from training knowledge through 2026-01 —
re-pulse live when possible):

- Captions are table stakes: most feed viewing is sound-off; high-energy ads
  caption EVERY sentence with big bold text and per-word/keyword color pops
  (the CapCut/variety-show look). url-ad does this via
  `--caption-coverage all` + brand-color accents.
- The hook is visual AND textual inside ~2-3s: state the value proposition on
  screen immediately; pattern-interrupt openings outperform brand intros.
- Authentic beats corporate: conversational VO, real product pixels
  (our faithful page capture) over stock footage and motion-graphics gloss.
- Constant motion: a cut or camera move every ~1.5-3s. The Ken-Burns slideshow
  must always be moving; static holds read as dead air.
- Native vertical 9:16, 1080x1920, content inside the platform safe zones
  (subtitles.py already applies per-format margins).
- Music carries energy: BGM mood matched to the ad's pacing, ducked under the
  voice (audio_mix.py sidechain ducking). Never silent.
- Length: 20-40s converts best for direct-response shorts; end with the CTA
  spoken AND burned on screen.

## C. Direction routing — pick ONE family

| Family | Hook pattern | Best for | BGM mood hint |
|---|---|---|---|
| problem-solution | name the pain, resolve with product | tools/SaaS/services (default) | rising, optimistic |
| demo-forward | "이것 보세요" -> fast feature run | strong visual UI/product | upbeat electronic |
| listicle | "N가지 이유/기능" countdown | 3+ distinct value_props | punchy, rhythmic |
| before-after | the transformation gap | results-driven products | dramatic build |
| question-hook | curiosity question the product answers | novel category products | playful, curious |

Tie-breaks: page is a utility/tool -> problem-solution; screenshots show a rich
UI -> demo-forward; >= 3 strong value_props of equal weight -> listicle.

## D. Dials (declare with the family)

- energy: calm | lively | hype (default lively for 9:16 ads)
- caption coverage: all (ads default) | key (calmer 16:9 embeds)
- pacing: seconds per scene 2-4 (lively) vs 4-6 (calm)
- formality: 해요체 conversational (default) | 합니다체 corporate

Pass the routed direction to the script stage as one compact string:

```
--style-direction "problem-solution, lively, 해요체: open on the pain of <X>,
resolve with <brand>, close on '<cta_text>'"
```

## D2. Visual direction (user-validated 2026-06-10)

What made the difference between a flat ad and a good one, in priority order:

1. **Scene-per-sentence sync**: every narration sentence gets its own shot of
   the screen it talks about, cut to that sentence's spoken duration. This is
   the single biggest dynamism lever — more than zoom strength or BGM.
2. **Show the product DOING things**: click into features and capture the
   screens where the product acts (an exercise card, a live conversation, a
   filled form). A menu/landing shot says what exists; a feature screen shows
   what it feels like. Type sample input into empty forms.
3. **Content fills the frame**: crop to the content region; let the blurred
   cover background supply depth. Empty page background reads as dead air.
4. Alternate pan direction per scene; keep a cut every ~2-3s.

See `workflows/url-ad.md` Stage 2 for the build steps.

## E. Anti-slop rules for ad copy

- Every claim traceable to `page_facts.json`; no invented features, numbers,
  prices, or superlatives ("최고의", "혁신적인") without a grounding fact.
- No filler openings ("안녕하세요", "오늘은 ... 소개합니다") — the hook IS the
  first sentence.
- One idea per sentence; short TTS-clean Hangul sentences.
- The CTA sentence is verbatim-stable (it must survive into key_sentences for
  the caption gate).

## F. Verify (role-separated)

1. Deterministic floor — `stage_gates.gate_ad_quality` (runs in the pipeline):
   hook within the ~3.5s speech window, total inside the 12-60s budget,
   key_sentences verbatim, closing CTA captioned. A failing script never
   reaches render.
2. Independent critic (fresh re-read, no edits): re-read `page_facts.json` +
   the script and check what the gate cannot — grounding (each claim maps to a
   fact), energy matches the declared dials, the family's hook pattern actually
   landed. Loop writer->critic at most 3 times; on the 3rd failure stop and
   report instead of shipping a weak script.
