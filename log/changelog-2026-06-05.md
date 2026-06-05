# Changelog 2026-06-05

## Restructure: intent-routed multi-workflow skill + url-ad spec

### Why
The skill is being repositioned toward the "paste a URL -> marketing video"
category (clickcast.tech). A deep-research run + repo gap analysis found the
backend (storyboard -> Flow -> TTS -> BGM -> captions -> upload) is solid and
actually ahead of commodity tools on reliability/gates, but the product had no
URL "front door", and its real modes (product-ad, commercial) were buried as
prose sections inside one monolithic SKILL.md. The user asked to separate each
form of video generation into its own workflow and route by intent — modeled on
the supergoal skill's "Step 0 — Mode" router.

### Decisions
- **Router lives in SKILL.md (agent-level), like supergoal** — not a Python
  `--mode` dispatcher this pass. SKILL.md became a Step-0 workflow table +
  shared contracts; per-workflow detail moved to `references/workflows/*.md`,
  loaded on demand. Lowest risk to the working orchestrator.
- **Three workflows**: `url-ad` (new), `idea-video` (the existing 7-stage flow),
  `product-ad` (existing product_ad + commercial modes merged).
- **URL ingestion = reuse existing Playwright** (no Firecrawl/Urlbox/fal paid
  APIs). The repo already solves attach/CDP/`run-code`; the managed-API
  alternative was researched and deliberately not adopted.
- **Scope this pass = "router + spec first"** (user choice): restructure +
  workflow docs + a tested gate + an honest Stage 0 scaffold. The heavy pieces
  (browser fetch helper, write_script grounding, orchestrator `--mode`) are the
  next build pass, tracked in `references/workflows/url-ad.md` Status table.

### Changes
- `SKILL.md`: rewritten as a router. New `<overview>` + `<workflows>` Step-0
  table; shared `<browser_attach>`/`<gates>`/`<requirements>`/
  `<important_constraints>`/`<files>`/`<validation>` kept (browser_attach +
  gates extended for the url-ad ingest stage); frontmatter description now
  covers all three workflows and the "paste a URL" entry phrase. Workflow-
  specific `<objective>`/`<quick_start>`/`<process>`/`<product_ad_mode>`/
  `<commercial_mode>` relocated (verbatim) into the workflow docs.
- `references/workflows/idea-video.md`, `product-ad.md`: relocated existing
  content (no behavior change).
- `references/workflows/url-ad.md`: NEW full spec — pipeline, page_facts.json
  contract, evidence-backed hook->USP->CTA script structure (TikTok first-party,
  3-0 confirmed), 9:16 default, reuse map, and honest caveats (16:9 conversion
  evidence is an open question; grounding-reduces-hallucination is a hypothesis).
- `scripts/stage_gates.py`: added `gate_page_facts` (consumer-side gate for the
  url-ad ingest stage), self-contained and style-matched to the JSON gates.
- `tests/test_stage_gates.py`: added RED/GREEN tests for `gate_page_facts`
  (valid pass; empty value_props / blank cta_text / non-object fail).
- `scripts/ingest_url.py`: NEW scaffold — argparse CLI + `PAGE_FACTS_SCHEMA`;
  `--help` works; a real run exits non-zero with a clear "pending" message
  (no faked artifact).

### Verified
- `pytest -q tests/test_stage_gates.py -k page_facts` RED before / GREEN after.
- `python3 scripts/ingest_url.py --help` exits 0; a real run prints
  `{"ok": false, ...}` and exits 2 (honest scaffold).
- Full suite + `scripts/*.py --help` parse loop: see this run's terminal output.

### Next pass (url-ad build)
1. `scripts/js/fetch_url_artifacts.tmpl.js` + wire `ingest_url.py` live capture
   (navigate URL -> OG/meta + readable text + screenshots; codex -> page_facts).
2. `write_script.py`: `--page-facts-json` grounding + hook(<=6s)/proposition
   (<=3s) -> USP -> CTA scaffold + `--aspect-ratio` (default 9:16); thread
   `--aspect-ratio` to `make_storyboard.py` (currently hardcoded 16:9).
3. `auto_youtube_pipeline.py`: `--mode {idea-video,url-ad,product-ad}` dispatcher
   + `--url`; insert Stage 0 before the script stage for url-ad.
