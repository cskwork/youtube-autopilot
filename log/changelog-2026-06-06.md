# Changelog 2026-06-06

## url-ad build pass: URL -> grounded marketing video

Implements the pieces the 2026-06-05 router/spec pass deferred (see
`references/workflows/url-ad.md` Status). Ingestion reuses the existing
Playwright automation (no paid APIs), per the prior decision.

### Changes
- **write_script.py** (Part A): added `--page-facts-json` and `--aspect-ratio`.
  `build_prompt` now injects a MARKETING GROUNDING block (facts-only) and the
  evidence-backed HOOK -> USP -> CTA structure (proposition <=3s, hook <=6s,
  CTA = page's cta_text) when page facts are supplied; a `_aspect_note` adapts
  pacing for 9:16 vs 16:9. Output schema unchanged. New offline tests in
  `tests/test_write_script.py`.
- **auto_youtube_pipeline.py** (Parts B+D):
  - Thread `--aspect-ratio` to `make_storyboard` (`--aspect`, previously ignored
    — fixes the storyboard-ignores-aspect bug) and to `write_script`; pass
    `--page-facts-json` when present.
  - `--mode {idea-video,url-ad}` + `--url` + `--page-facts-json`. `run_pipeline`
    is now a dispatcher (`getattr(args,"mode","idea-video")`, so existing callers
    and `test_pipeline_gates` are unaffected); the 7-stage body moved to
    `run_pipeline_idea_video`.
  - New `run_pipeline_urlad`: ingest -> grounded script -> real-page slideshow
    -> narration -> upload, with the gate after every stage (`gate_page_facts`,
    `gate_script`, `gate_video`, `gate_narration`). No AI storyboard, no
    Flow/delogo. New stages: `stage_ingest`, `_urlad_idea_storyboard` (derives
    the minimal idea/storyboard write_script needs from page facts),
    `stage_visuals_slideshow` (build_slideshow over the captured screenshots,
    sized to a narration-length estimate).
- **ingest_url.py** (Part C): scaffold -> live capture. Reuses
  `google_flow_cli` attach/cmd/run/_json_result; runs
  `js/fetch_url_artifacts.tmpl.js` to pull OG/meta + readable text + N viewport
  screenshots, writes them as `scene_*.png`, and codex-distills the raw
  extraction into the page_facts contract. Pure helpers (`render_fetch_js`,
  `write_screenshots`, `assemble_page_facts`, `build_distill_prompt`) are
  offline-tested in `tests/test_ingest_url.py`.
- **scripts/js/fetch_url_artifacts.tmpl.js** (NEW): `page => (async ...)`
  template (NODE context); `page.goto` + `page.evaluate` DOM read + scrolling
  `page.screenshot` returning base64 shots; never throws.

### Verified (offline)
- `pytest -q`: 124 passed (was 108). New: 4 build_prompt, 6 ingest_url, 6
  url-ad wiring tests; each new gate/helper has RED->GREEN coverage.
- All `scripts/*.py --help` parse clean.
- Real smoke: `build_slideshow.py` over two `scene_*.png` at 1080x1920 produced a
  6.0s 1080x1920 MP4 (the url-ad visuals path, no browser/codex).

### NOT verified by the author (needs a human-approved live run)
A full url-ad run needs an attached Chrome (browser ingest), a logged-in codex
(script + fact distillation), and Supertonic (TTS) — the same external deps as a
real idea-video run. Run:
`python3 scripts/auto_youtube_pipeline.py --mode url-ad --url "<page>" --aspect-ratio 9:16 --out-dir ./out`
and confirm capture fidelity + that the script is grounded (no invented
features) with a 3s proposition / 6s hook / matching CTA. Log any selector or
prompt fixes in `references/improvement_log.md`.

### Possible refinements (not blocking)
- Visuals: slideshow length is estimated from narration char count, then
  `add_narration` freeze-pads to the real TTS length (a long tail holds the last
  shot). A TTS-first ordering would let visuals span the exact narration.
- Mix Flow/AI B-roll via `build_kenburns_clip` + `assemble_flow_video` (hybrid),
  currently the product-ad path only.
