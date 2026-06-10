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
| Creative direction system (`references/ad-creative.md`) + `--style-direction` | DONE (`tests/test_write_script.py`) |
| `stage_gates.gate_ad_quality` (hook/duration/captioned-CTA) + chain wiring | DONE (`tests/test_stage_gates.py`, `tests/test_pipeline_urlad.py`) |
| Full-coverage captions + brand-color accents (`--caption-coverage all`, `--brand-colors`) | DONE (`tests/test_subtitles.py`, `tests/test_pipeline_urlad.py`) |
| Ken-Burns auto fit axis for wide content crops | DONE (`tests/test_kenburns.py`) |
| Scene-per-sentence visuals (interactive capture + crop + sync) | DONE as an agent-driven path (worked example `out/engstt-ad`, user-validated); orchestrator wiring TODO |

Offline-verified: every pure helper + the full gate/stage wiring (with stubbed
producers) + the slideshow render over real screenshots. NOT yet verified by the
author: a full LIVE run, which needs an attached, human-approved Chrome (browser
ingest), a logged-in codex (script + fact distillation), and Supertonic (TTS) —
the same external dependencies as a real idea-video run. Run it live to confirm
capture fidelity and script quality, then log fixes in `improvement_log.md`.

## Pipeline

The video is made FROM the page. Stages 2-4 reuse existing scripts unchanged;
only Stage 0 and the grounding in Stage 1 are new.

0. **Ingest** (`ingest_url.py`, Playwright, no paid API): LAUNCH a fresh agent
   browser (`--capture-mode launch`, the default) — a public page needs no
   logged-in session, so there is no attach/human step; `ingest_url` opens its
   own Chrome-for-Testing, captures, and closes it. Navigate the URL, extract
   Open Graph/meta + readable text, and screenshot the page while scrolling
   (`page.evaluate()` + `page.screenshot()`); codex then distills the raw
   extraction into `page_facts.json` (the schema below). Gate: `gate_page_facts`.
   - For a page behind a login, use `--capture-mode attach` to drive the user's
     logged-in Chrome instead (see `<browser_attach>` in `SKILL.md`).
   - Capture engine decision: reuse the existing Playwright agent CLI (the repo
     already solves launch/attach/`run-code`); no Firecrawl/Urlbox/fal paid APIs.
     The browser helper mirrors the `google_flow_cli.py` template pattern
     (`run-code --filename <generated.js>` with JSON-literal placeholder
     substitution); the returned JSON is decoded UTF-8-safe (`parse_runcode_json`,
     NOT unicode_escape, which mangles Hangul). JS-heavy / auth-gated pages can
     still render incompletely; surface a clear error rather than thin facts.
0.5. **Creative direction** (`references/ad-creative.md`, agent step, no code):
   read the brief from `page_facts.json` (one line), pulse current short-form
   ad trends (dated; baked snapshot fallback), route to ONE ad style family
   (problem-solution / demo-forward / listicle / before-after / question-hook)
   and declare the dials (energy, caption coverage, pacing, formality). Pass
   the routed direction via `--style-direction` so codex writes inside it.
1. **Script — grounded + conversion-structured** (`write_script.py`, extended):
   feed `page_facts.json` so codex writes narration CONSTRAINED to the page's
   real facts (no invented features) and on the evidence-backed structure below,
   inside the routed creative direction. Output is the existing `script.json`
   (narration_ko, flow_prompt, scene_prompts, bgm_mood, key_sentences,
   youtube{...}); aspect-ratio aware, default 9:16. Gates: `gate_script` then
   `gate_ad_quality` — the deterministic ad floor (opening sentence inside the
   ~3.5s hook speech window, total inside the 12-60s short-form budget, every
   key sentence verbatim in the narration, the closing CTA sentence captioned).
   A weak script hard-stops BEFORE any render. On gate failure, fix the script
   (re-run codex with the gate's message folded into `--style-direction`) and
   re-gate; after 3 failures stop and report — never ship around the gate.
   An independent critic pass (fresh re-read; `ad-creative.md` section F)
   covers what the gate cannot: claim-by-claim grounding and energy match.
2. **Visuals — scene-per-sentence real-UI B-roll** (PREFERRED; user-validated
   2026-06-10): real pixels only, never re-rendered by a generative model.
   No Flow, no delogo. Gate: `gate_video`. Build it in four steps:
   1. **Interactive capture**: scrolling screenshots of a short page are five
      copies of the same menu — instead, drive the launched browser with a
      one-off `run-code` script (mirror `out/<run>/_capture_features*.run.js`
      from the worked example; same `flow.cmd`/`run-code --filename` pattern
      as ingest) that CLICKS into each feature and one level deeper (topic ->
      exercise screen, role pick -> conversation), and TYPES a plausible
      sample into empty forms so screens look in-use. Capture at a mobile
      viewport (~720px) so layouts compact.
   2. **Content crop**: crop each shot to its content region (cut empty
      page background, error toasts, dead whitespace) so the product fills
      the frame; `build_kenburns_clip` lays the sharp crop over a blurred
      depth background (auto fit axis: wide crops fit by width).
   3. **Scene-per-sentence sync**: one Ken-Burns clip PER NARRATION SENTENCE,
      each clip's duration taken from the per-sentence caption timings
      (captions.srt of a previous narration pass, or the TTS segment times),
      pan direction alternating per scene (`--reverse` on odd scenes), then
      ffmpeg-concat. Every sentence shows the screen it talks about and a cut
      lands every ~2-3s — this sync is what makes the ad read as dynamic.
   4. Map scenes to the script structure: hook -> menu/hero, each USP ->
      its feature screen (in narration order), CTA -> the screen the
      `cta_text` points at.
   - Fallback (`build_slideshow.py`, orchestrator default `--mode url-ad`):
     plain Ken-Burns slideshow over the scrolling ingest screenshots, sized to
     the narration estimate. Acceptable for long content-rich pages; weak for
     short menu-like pages. Orchestrator wiring of the preferred path is a
     TODO (`improvement_log.md`).
3. **Narrate + music + captions** (`add_narration.py`): per-sentence Supertonic
   TTS + ducked royalty-free BGM + format-aware burned captions. url-ad runs
   FULL-coverage captions (`--caption-coverage all` — every sentence burned,
   sound-off viewers carried) with brand-color accents from
   `page_facts.brand_colors` (`--brand-colors`; too-dark colors are skipped
   for legibility). The orchestrator wires both automatically
   (`_urlad_caption_args`). Gate: `gate_narration`.
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
python3 -m pytest tests/test_stage_gates.py -k "page_facts or ad_quality" -q  # gates RED/GREEN
python3 -m pytest tests/test_subtitles.py -k "coverage or brand" -q           # caption modes
python3 scripts/ingest_url.py --help                                          # CLI contract
```

End-to-end (launches a fresh agent browser for ingest — no attach needed for a
public page; still needs a logged-in codex and Supertonic for script + TTS):

```bash
python3 scripts/auto_youtube_pipeline.py --mode url-ad \
  --url "https://example.com" --aspect-ratio 9:16 --allow-synth-bgm --out-dir ./out
ffprobe -v error -show_entries format=duration -show_entries \
  stream=width,height -of default=nw=1 ./out/narrated.mp4
```

Add `--dry-run` to skip the upload (the video `./out/narrated.mp4` is produced
before the upload stage). To re-use already-captured facts and skip ingest, pass
`--page-facts-json ./out/page_facts.json` (its `page_facts_shots/` must sit
beside it).

Confirm `page_facts.json` reflects the real page (no invented features), the
first ~3s states the proposition, an explicit hook lands by ~6s, the CTA matches
`cta_text`, and the real screenshots appear faithfully (not garbled by Flow).
