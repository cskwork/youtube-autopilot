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

## url-ad: launch mode (no attach) + first live run

Follow-up the same day. The url-ad ingest should NOT need the user's logged-in
Chrome — a public page can be captured by a fresh agent browser.

- ingest_url: added `--capture-mode {launch,attach}` (default launch) +
  `--reuse-session`. `launch` runs `@playwright/cli ... open <url>` to start a
  fresh Chrome-for-Testing, captures, and closes it — no attach/human step.
  `attach` keeps the logged-in path for pages behind a login. Orchestrator
  `stage_ingest` passes `--capture-mode launch`.
- ingest_url: added `parse_runcode_json` (UTF-8-safe) replacing
  `google_flow_cli._json_result` for the fetch result — `unicode_escape` mangled
  Hangul (티스토리 -> mojibake). Tested.
- ingest_url: fixed `DISTILL_SCHEMA` to list every property in `required`
  (OpenAI strict structured-output rejects partial `required`); strengthened the
  distill prompt so `cta_text` is always non-empty (infer the primary action)
  and features prefer real capabilities over bare nav labels.
- Docs: SKILL.md `<browser_attach>` now documents launch vs attach;
  `references/workflows/url-ad.md` Stage 0 + verification updated.

### First live run (tistory.com) — verified
Produced a real ad: `out/narrated.mp4`, 1080x1920 (9:16), 188.9s, 25.4 MB,
H.264+AAC; `gate_narration` passed (mean_volume -25.5 dBFS, not silent). The
codex script was grounded in the real page facts (no invented features), opened
with the value proposition, and closed on the CTA "티스토리에서, 나를 표현해 보세요."

Environment note: the user's `~/.codex/config.toml` `[agents]` block
(`model_provider = "headroom"`, scalar keys) is invalid for codex-cli 0.137.0 and
blocks EVERY codex call (`invalid type: string "headroom", expected struct
AgentRoleToml`). Worked around non-destructively with an isolated
`CODEX_HOME=/tmp/codex_home_clean` (copied auth.json + empty config.toml); the
user should fix the global `[agents]` section for the skill to run normally.

Open refinements surfaced by the run:
- 3.1-min narration is long for short-form; tighten the script for 9:16 (fewer
  features, ~30-60s) and capture more screenshots (4 shots -> ~47s each = static).
- Add a `--no-upload` for url-ad: the run exits 1 at the upload stage when no
  YouTube token/secret exists, even though the video is already produced.

## url-ad v2: short-form + more shots + real BGM (same day)

Addresses the two issues the first live run surfaced (BGM inaudible; scenes not
tracking the speech; video too long).

- Short-form scripting: `_urlad_idea_storyboard` now derives one scene per top
  value prop (cap 5), NOT every feature — so write_script's pacing target drops
  to ~40s; the grounding prompt also instructs a 30-45s, top-3-4-props narration
  (no feature enumeration). Result: 188.9s -> 23.2s.
- More, synced visuals: `stage_ingest` captures `--max-shots 8` (was 4) so the
  Ken-Burns slideshow changes shots in step with the short narration.
- Real BGM: with `JAMENDO_CLIENT_ID` set, the BGM stage downloads a real CC-BY
  track for the script's `bgm_mood` (cached under references/bgm_cache/) and
  writes `CREDITS.txt` — replacing the near-silent synth sine pad. (Client id is
  a public identifier; stored as an env var in the user's shell profile, never
  in code. Jamendo's tracks API needs only the client id, not the secret.)
- `--no-upload`: `run_pipeline_urlad` skips the upload stage and exits 0 with the
  local video (the flag already existed for idea-video). url-ad is file-first.
- ingest_url quality: distill prompt now guarantees a non-empty `cta_text`
  (inferred if no explicit button) and prefers real capabilities over nav labels.

Second live run (tistory.com): `out/narrated.mp4`, 1080x1920, 23.2s, 8 real page
screenshots, grounded 4-sentence script ending on the CTA "지금, 나의 티스토리
보기.", real Jamendo BGM ducked under the narration, clean exit 0. Tests: 126
passed.
