# Workflow: url-ad

"No recording, no editing — just paste a URL." Turn a website / landing /
product page into a short marketing/demo video. Routed from `SKILL.md` Step 0
when a URL is the input and the page itself should appear on screen. Reuses the
shared building blocks and contracts in `SKILL.md`; only the FRONT of the
pipeline (what the video is made FROM) is new.

This is the workflow that targets the clickcast.tech category. The market has
already validated the UX (paste URL -> AI scripting -> voice + motion -> multi
-format output), so the edge is execution quality, not the flow: source-grounded
scripting (no invented features), faithful real-page capture as B-roll (vs
generic stock footage), and caption/pacing tuned to the hook window.

## Status

| Piece | State |
|---|---|
| Workflow spec (this doc) | DONE |
| `stage_gates.gate_page_facts` + tests | DONE (`tests/test_stage_gates.py`) |
| `write_script.py` grounding + hook->USP->CTA + `--aspect-ratio` | DONE (`tests/test_write_script.py`) |
| `make_storyboard`/`write_script` aspect-ratio threading | DONE (orchestrator) |
| `scripts/ingest_url.py` live capture + codex distillation | DONE; pure helpers tested (`tests/test_ingest_url.py`) |
| `scripts/js/fetch_url_artifacts.tmpl.js` (browser fetch) | DONE |
| `auto_youtube_pipeline.py` `--mode url-ad` pipeline + gate chain | DONE; wiring tested (`tests/test_pipeline_urlad.py`) |

Offline-verified: every pure helper + the full gate/stage wiring (with stubbed
producers) + the slideshow render over real screenshots. NOT yet verified by the
author: a full LIVE run, which needs an attached, human-approved Chrome (browser
ingest), a logged-in codex (script + fact distillation), and Supertonic (TTS) —
the same external dependencies as a real idea-video run. Run it live to confirm
capture fidelity and script quality, then log fixes in `improvement_log.md`.

## Pipeline

The video is made FROM the page. Stages 2-4 reuse existing scripts unchanged;
only Stage 0 and the grounding in Stage 1 are new.

0. **Ingest** (`ingest_url.py`, NEW — Playwright, no paid API): drive the SAME
   attached Chrome used for Flow/Studio (see `<browser_attach>` in `SKILL.md`)
   to navigate the URL, extract Open Graph/meta tags + readable page text, and
   screenshot the page (hero + a few key sections) via `page.evaluate()` +
   `page.screenshot()`. codex then distills the raw extraction into
   `page_facts.json` (the schema below). Gate: `gate_page_facts`.
   - Capture engine decision: reuse existing Playwright automation (the repo
     already solves attach/CDP/`run-code`); no Firecrawl/Urlbox/fal paid APIs.
     The new browser helper mirrors the `google_flow_cli.py` template pattern
     (`run-code --filename <generated.js>` with JSON-literal placeholder
     substitution). JS-heavy / auth-gated pages can still fail to render fully;
     surface a clear error rather than producing thin facts.
1. **Script — grounded + conversion-structured** (`write_script.py`, extended):
   feed `page_facts.json` so codex writes narration CONSTRAINED to the page's
   real facts (no invented features) and on the evidence-backed structure below.
   Output is the existing `script.json` (narration_ko, flow_prompt,
   scene_prompts, bgm_mood, key_sentences, youtube{...}); add aspect-ratio
   awareness and default to 9:16. Gate: `gate_script`.
2. **Visuals — real page as B-roll** (`build_slideshow.py`, implemented default):
   the captured screenshots (saved as `scene_*.png`) are rendered into a
   Ken-Burns slideshow sized to an estimate of the narration length; the real
   pixels are shown faithfully, never sent through a generative model. No Flow
   and no delogo — the real page IS the visual. Gate: `gate_video`.
   - Future enhancement: mix Flow/AI atmosphere B-roll by routing each shot
     through `build_kenburns_clip.py` and concatenating with `assemble_flow_video.py`
     (delogo Flow clips only) — the same hybrid rule as `product-ad`. Not wired
     yet; the slideshow path is the current default.
3. **Narrate + music + captions** (`add_narration.py`, unchanged): per-sentence
   Supertonic TTS + ducked royalty-free BGM + format-aware burned key captions.
   Gate: `gate_narration`.
4. **Output**: a file by default (`narrated.mp4` + sidecars). Upload is optional
   and reuses Stage 7 (`upload_youtube*.py`), private-by-default, same human
   publish gate as `idea-video`.

## page_facts.json contract

Produced by Stage 0, verified by `gate_page_facts`, consumed by Stage 1. See
`PAGE_FACTS_SCHEMA` in `scripts/ingest_url.py` for the authoritative field list.

```json
{
  "url": "https://example.com",          // required, non-empty
  "title": "Example — do X in seconds",  // required, non-empty
  "brand": "Example",
  "value_props": ["Save hours", "No editing"],  // required, >=1 (USP source)
  "features": ["One-click export", "40 languages"],
  "cta_text": "Start free",              // required, non-empty (CTA slot)
  "cta_url": "https://example.com/signup",
  "brand_colors": ["#1a1a2e", "#e94560"],
  "screenshots": ["page_facts/hero.png", "page_facts/features.png"]
}
```

The gate requires `url`, `title`, `cta_text` (non-empty strings) and
`value_props` (a non-empty list) — the minimum to ground a hook -> USP -> CTA
script. The rest are optional enrichment.

## Evidence-backed script structure (Stage 1)

From TikTok's first-party advertiser guidance (deep-research, 3-0 confirmed):

- Front-load the value PROPOSITION into the first ~3 seconds (recall), and land
  an explicit HOOK within the first ~6 seconds (engagement/watch time).
- Default storyboard scaffold: **hook -> unique selling points -> clear CTA.**
  Map `value_props`/`features` into the USP slot and `cta_text` into the CTA.
- Baseline specs: vertical **9:16**, >= 720P (1080x1920 recommended), always
  include sound/music, keep content in the UI safe zone (captions already do
  per-format safe margins in `subtitles.py`).

These are programmatically enforceable constraints to bake into the codex prompt
(timing windows + structure + the verbatim CTA).

## Defaults

- Aspect ratio: **9:16 by default** (the conversion evidence is strongest for
  short-form vertical); 16:9 optional for landing-page embeds.
- BGM on, captions on, private-by-default if uploading — same as the shared
  contract in `SKILL.md`.

## Caveats / open questions (do not over-claim)

- **16:9 long-form** structure/length/hook guidance is an OPEN question — the
  research surfaced no verified, evidence-backed 16:9 conversion claims. Treat
  16:9 as secondary until validated.
- **Source-grounding reduces hallucination** is a reasonable design hypothesis,
  NOT a verified best practice (the proposed grounding gate failed verification
  1-2). For a product demo it is still necessary to avoid claiming features the
  page does not have, but do not market it as a proven conversion lever.
- **"Any URL" capture is optimistic**: JS-heavy or auth-gated pages can render
  incompletely. Fail with a clear message rather than thin/empty facts.
- **TTS engine choice** for non-Korean marketing copy is unsettled: the
  Cartesia-vs-others latency/quality claims were all refuted; benchmark before
  swapping Supertonic for multilingual output. Supertonic is Korean-focused.

Sources behind these points live in the deep-research run for this workflow
(TikTok creative best-practices: primary; MoneyPrinterTurbo/Metascraper/
Firecrawl/Urlbox/fal/Remotion: primary, captured as the managed-API alternative
we deliberately did NOT adopt this pass).

## Verification (once the pending pieces land)

Offline, now:

```bash
python3 -m pytest tests/test_stage_gates.py -k page_facts -q   # gate RED/GREEN
python3 scripts/ingest_url.py --help                           # CLI contract
```

End-to-end (next pass, needs an attached Chrome — a human-approved browser run,
same gate as `idea-video`):

```bash
python3 scripts/auto_youtube_pipeline.py --mode url-ad \
  --url "https://example.com" --aspect-ratio 9:16 --out-dir ./out
ffprobe -v error -show_entries format=duration -show_entries \
  stream=width,height -of default=nw=1 ./out/narrated.mp4
```

Confirm `page_facts.json` reflects the real page (no invented features), the
first ~3s states the proposition, an explicit hook lands by ~6s, the CTA matches
`cta_text`, and the real screenshots appear faithfully (not garbled by Flow).
