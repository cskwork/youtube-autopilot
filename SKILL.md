---
name: youtube-autopilot
description: Intent-routed automated video-generation pipeline. Step 0 classifies the request into ONE of three workflows and loads its spec from references/workflows/, then composes shared building blocks to a finished video. (1) url-ad — "no recording, no editing, just paste a URL": ingest a website/landing/product page (Playwright scrape of Open Graph/meta + readable text + screenshots), ground a hook->USP->CTA script in the real page facts, show the captured page as faithful B-roll, and narrate it — the clickcast.tech category. (2) idea-video — the unattended "idea to private YouTube draft" flow that harvests the Studio inspiration feed (or a --topic), storyboards via codex, renders Gemini/Google Flow clips, delogos the watermark, narrates in Korean with Supertonic TTS, and uploads a PRIVATE draft. (3) product-ad — advertise an existing app/site whose real UI must appear faithfully (hybrid real-screen Ken-Burns + Flow B-roll), including a one-shot 30s vertical app commercial. Shared across workflows: Google Flow render (or slideshow fallback), per-sentence Supertonic narration, royalty-free ducked BGM, format-aware burned captions, gated fail-fast stages, and private-by-default upload. Use whenever the user wants a marketing/YouTube video made automatically — from a URL, an idea/topic, or an existing product.
---

<overview>
youtube-autopilot makes a finished video automatically. It is intent-routed: the
SAME building blocks (Flow render or slideshow, Supertonic narration, ducked
royalty-free BGM, format-aware captions, gated stages, private-by-default upload)
are composed by one of three workflows. Only the FRONT of the pipeline — what the
video is made FROM — differs. Pick the workflow first, then follow its spec.
</overview>

<workflows>
Step 0 — classify the request into ONE workflow, state it to the user in one
line, then load its spec from `references/workflows/`. Do not inline a workflow's
detail here; load the file.

| Signal in the request | Workflow | Load |
|---|---|---|
| A pasted link; "turn this URL / website / landing / product page into a video/ad/demo"; "no recording, just paste a URL" | **url-ad** | `references/workflows/url-ad.md` |
| "idea to draft"; a short from my Studio inspiration feed; `--topic ... -> YouTube`; trending-seeded; "re-run one stage" | **idea-video** | `references/workflows/idea-video.md` |
| "advertise my app/product (real UI must show faithfully)"; "30s app commercial"; user supplies real screen captures | **product-ad** | `references/workflows/product-ad.md` |

Tie-breakers: when a URL is the input and the page itself should appear on
screen, prefer **url-ad**; when the user supplies real screen captures or the
product has no public URL, prefer **product-ad**; the **idea-video** flow is the
default for inspiration/topic-seeded YouTube drafts. If still ambiguous, ask one
question.

All three share the contracts below (`<browser_attach>`, `<gates>`,
`<requirements>`, `<important_constraints>`, `<files>`, `<validation>`).
</workflows>

<browser_attach>
The browser stages (URL ingest, harvest, Flow video, Studio upload) drive ONE
logged-in Chrome session via the Playwright agent CLI. Proven setup (Chrome 148,
macOS):

1. Chrome 148 ignores `--remote-debugging-port` on the default profile. Enable
   it via the UI instead: open `chrome://inspect/#remote-debugging` and turn on
   "Allow remote debugging for this browser instance" (serves 127.0.0.1:9222).
2. Attach once: `npx @playwright/cli@latest attach --cdp=chrome -s=vya`.
3. Use ONE session for every stage (`--session vya --no-attach`) so it stays a
   single browser.
4. ALWAYS use the system npm cache (empty `--npm-cache`). A custom cache pulls a
   different @playwright/cli version whose daemon cannot see the attached
   session — the #1 silent failure (scrapes return parse errors).
5. `run-code` runs `page => ...` in NODE context; DOM scraping must live inside
   `page.evaluate(() => {...})`, and `process` is unavailable in that sandbox.
6. AGENT APPROVAL REQUIRED. Every browser stage shells out to
   `npx @playwright/cli@latest` (an external package), and the attach + upload is
   an outward-facing, credit-spending, hard-to-reverse action. In an agent
   harness (e.g. Claude Code) the auto-permission classifier BLOCKS this by
   default, so a live run cannot proceed unattended — the human MUST explicitly
   approve it. A one-time attach approval is NOT enough: URL ingest, harvest,
   Flow video, and Studio upload each re-invoke the CLI, so grant a standing
   allow rule for `npx @playwright/cli@latest *` (or run the attach yourself via
   the shell `!` prefix and approve each subsequent stage). Treat this as a
   deliberate human gate before any real credit spend or upload, never a step to
   work around.
</browser_attach>

<gates>
`scripts/stage_gates.py` is the teeth behind "each stage must pass". After every
stage the orchestrator re-inspects the produced artifact and raises a hard stop
on any degradation, so a failure (video gen, audio gen, etc.) NEVER carries
forward or uploads:

- harvest -> `gate_ideas`: ideas.json parses and has >= idea-index+1 ideas.
- storyboard -> `gate_storyboard`: storyboard.json parses and >= 1 real
  `scene_*.png` frame exists (catches gen.sh image failures).
- script -> `gate_script`: non-empty `narration_ko` and `flow_prompt`.
- video -> `gate_video`: file present, a real video stream, duration above a
  floor, non-trivial size (catches truncated/zero-byte/streamless Flow output).
- delogo -> `gate_video`: the delogo output is still a real video.
- narration -> `gate_narration`: video AND audio streams present, duration sane,
  and the audio is NOT effectively silent (ffmpeg `volumedetect` mean dBFS above
  the silence threshold). This catches the TTS-silent-failure that the
  `{"tts": true}` flag cannot. `add_narration.py` self-applies the same check.
- url-ad ingest -> `gate_page_facts`: page_facts.json parses to an object with a
  non-empty `url`, `title`, `cta_text` and >= 1 `value_props` (the minimum to
  ground a hook->USP->CTA script).

Fallbacks are opt-in (real generation by default): the synthesized BGM pad needs
`--allow-synth-bgm`; otherwise a BGM-on run with no real track hard-stops with an
actionable message. Tune thresholds via `stage_gates.DEFAULT_SILENCE_DB` and the
per-gate `min_duration` / `min_bytes` args.
</gates>

<requirements>
- Python 3.12 with `pip install -r requirements.txt` (google-api-python-client,
  google-auth-oauthlib, google-auth-httplib2, pillow). Stage 6 BGM/subtitles add
  NO pip deps — they use only the Python stdlib (urllib) plus ffmpeg.
- `ffmpeg` and `ffprobe` on PATH (delogo, mux, duration, dry-run placeholder).
  Stage 6 additionally needs ffmpeg built with **libass** (the `ass`/`subtitles`
  filter, for burned captions) and the `sidechaincompress`, `afade`, and
  `amix` filters plus the `-stream_loop -1` input flag (the BGM bed loops via
  `-stream_loop -1` and is trimmed by `amix duration=first`, not `aloop`) —
  all present in stock ffmpeg 7.x.
- Optional `JAMENDO_CLIENT_ID` env var enables fresh per-run royalty-free BGM
  from Jamendo (CC-BY/CC-BY-SA/CC0 only). Absent/offline -> a synthesized CC0
  ambient pad guarantees BGM. Never hardcode the key; it is read from the env.
- `codex` CLI logged in via ChatGPT (`codex login status` => "Logged in using
  ChatGPT"); needs the `image_generation` entitlement for storyboards.
- Chrome with remote debugging, logged into the target Google account with
  access to BOTH YouTube Studio and Google Flow; the Playwright agent CLI
  attaches over CDP endpoint `chrome`.
- Node 18.3+ and npm for the Supertonic fallback and the Playwright agent CLI.
- A YouTube OAuth Desktop-app client secret JSON (passed via `--client-secret`,
  never hardcoded). One-time bootstrap: `scripts/get_youtube_token.py`. Token
  cache default: `~/.config/youtube-autopilot/token.json`.
</requirements>

<important_constraints>
- Fail-fast: every stage is gated (`<gates>`). The pipeline NEVER continues past
  a failed stage — a failed video gen, silent narration, empty harvest, or
  frameless storyboard hard-stops with `GATE FAILED after '<stage>'` and never
  uploads. Designed fallbacks (synth BGM) are opt-in, not silent.
- Upload privacy defaults to `private`. The pipeline NEVER auto-publishes; the
  only human step is flipping the draft to public in YouTube Studio.
- Each fresh Flow submit and each codex call may spend credits/tokens; prefer
  `--dry-run` to validate the chain before a real run.
- Human approval gate (live runs): the browser stages run `npx @playwright/cli`,
  an external package, and the attach/upload spends credits and is hard to
  reverse, so an agent harness will (and should) require explicit user approval
  before the live run. Grant a standing allow rule for the playwright CLI; do not
  bypass the gate. See `<browser_attach>` point 6.
- Secrets (OAuth client secret, token) come only from CLI args / files; nothing
  is hardcoded. The uploader never prints token/secret contents.
- Studio uses Shadow DOM + virtualized lists and Flow's DOM drifts; the scraper
  pierces shadow roots, scrolls, and falls back to youtube.com trending.
- Continuous improvement: when a Studio/Flow selector breaks or generated
  quality drifts, update the relevant selector/prompt and append a dated entry
  to `references/improvement_log.md`. The runbook in `references/runbook.md` has
  per-stage debug checklists.
</important_constraints>

<files>
Workflow specs (load per Step 0):
- `references/workflows/url-ad.md` — paste-a-URL marketing/demo video (the
  clickcast.tech category); ingest -> grounded hook->USP->CTA script -> real-page
  B-roll -> narrate. NEW; see its Status table for what is built vs pending.
- `references/workflows/idea-video.md` — the 7-stage "idea to private YouTube
  draft" orchestrator flow (the original pipeline).
- `references/workflows/product-ad.md` — hybrid real-UI + Flow B-roll ad and the
  one-shot 30s vertical app commercial.

Shared scripts:
- `scripts/auto_youtube_pipeline.py` — one-command end-to-end orchestrator;
  gates every stage, writes `manifest.json`, stops at the private draft.
- `scripts/stage_gates.py` — per-stage artifact verification (ffprobe/ffmpeg);
  raises `GateError` so the orchestrator hard-stops on any degraded output;
  includes `gate_page_facts` for the url-ad ingest stage.
- `scripts/ingest_url.py` — url-ad Stage 0 (SCAFFOLD): CLI + `PAGE_FACTS_SCHEMA`
  for the page-facts contract; live Playwright capture pending (see url-ad.md).
- `scripts/harvest_ideas.py` — idea-video Stage 1: Studio inspiration / trending
  -> ranked ideas via codex.
- `scripts/make_storyboard.py` — idea-video Stage 2: idea -> scene beats +
  storyboard PNGs.
- `scripts/write_script.py` — Stage 3: Korean narration + Flow prompts + YouTube
  metadata (will gain page-facts grounding for url-ad).
- `scripts/generate_video.py` — Stage 4: Flow render via `google_flow_cli.py`
  (call once per scene for a full-length video).
- `scripts/assemble_flow_video.py` — concat scene clips + delogo + fit to
  narration + mux into one MP4 (real Ken-Burns clips + Flow B-roll).
- `scripts/build_slideshow.py` — Flow-free fallback: narrated Ken-Burns video
  from stills (storyboard frames or url-ad screenshots).
- `scripts/build_kenburns_clip.py` — render ONE real screenshot as a faithful
  Ken-Burns clip (sharp UI, blurred-cover bg, fixed geometry) so real screens
  concat with Flow B-roll without being regenerated. Used by product-ad + url-ad.
- `scripts/generate_commercial.py` — product-ad one-shot 30s vertical app ad.
  Shares `google_flow_cli.py`; bundled SCENES are an editable template. Worked
  inputs in `examples/speakcoach/`.
- `scripts/remove_logo.py` — Stage 5: ffmpeg `delogo` watermark removal.
- `scripts/add_narration.py` — Stage 6 conductor: per-sentence Supertonic TTS +
  low BGM bed + ducking + selective burned key captions + ffmpeg mux.
- `scripts/subtitles.py` — Stage 6: Korean sentence split, per-sentence TTS
  timing, WAV concat, key-sentence selection, `.srt`/`.ass` builders, burn `-vf`.
- `scripts/bgm_library.py` — Stage 6: resolve one royalty-free track per run
  (explicit > cache > Jamendo > synth pad); license filter + attribution.
- `scripts/audio_mix.py` — Stage 6: pure ffmpeg mix-graph builder + runner
  (narration + low BGM bed + optional original audio + optional ducking).
- `scripts/upload_youtube.py` — Stage 7a: private YouTube Data API upload.
- `scripts/upload_youtube_studio.py` — Stage 7b: private upload by driving the
  Studio browser (no OAuth; proven path).
- `scripts/get_youtube_token.py` — one-time OAuth consent + token cache.
- `scripts/google_flow_cli.py` — vendored Flow browser-automation CLI.
- `scripts/js/` — browser helpers (`studio_inspiration.js`, `flow_*.js`,
  `studio_upload.tmpl.js`).
- `references/runbook.md` — per-stage operational + debug guide.
- `references/improvement_log.md` — living log of selector/prompt/failure fixes.
- `tests/test_remove_logo.py` — delogo box geometry unit tests.
- `tests/test_audio_mix.py` — pure BGM mix-graph builder assertions.
- `tests/test_subtitles.py` — Korean split, timing, key selection, caption files.
- `tests/test_bgm_library.py` — BGM resolution order + license filter (mocked).
- `tests/test_add_narration_integration.py` — offline Stage 6 end-to-end (stub
  TTS, real ffmpeg): asserts audio stream, duration, captions, CREDITS handling,
  synth-BGM opt-in, and the no-real-BGM hard stop.
- `tests/test_stage_gates.py` — gate RED/GREEN proofs on ffmpeg fixtures
  (good/no-audio/silent/truncated/short) plus the JSON/storyboard/page-facts gates.
- `tests/test_pipeline_gates.py` — orchestrator wiring: a degraded artifact
  (junk video / silent narration) hard-stops `run_pipeline` BEFORE upload.
</files>

<validation>
Confirm the orchestrator and every stage parse cleanly:

```bash
for f in scripts/*.py; do python3 "$f" --help >/dev/null || echo "FAIL: $f"; done
python3 -m pytest -q   # full suite, incl. test_stage_gates + test_pipeline_gates
```

The gate suite is the proof that "each stage must pass": `test_stage_gates.py`
shows each gate RAISES on a degraded artifact (no-audio / silent / truncated /
missing page facts) and PASSES a real one; `test_pipeline_gates.py` shows a
degraded stage output hard-stops the orchestrator before upload.

Reference end-to-end check (idea-video) without Flow credits or an upload.
`--dry-run` uses a 2s placeholder clip when no `--video` is supplied; add
`--allow-synth-bgm` (no Jamendo key) or `--no-bgm`, since BGM-on hard-stops
without a real track:

```bash
python3 scripts/auto_youtube_pipeline.py --topic "테스트" --dry-run --allow-synth-bgm
cat <out-dir>/manifest.json
```

After a real run, confirm the final MP4 and the private draft:

```bash
ffprobe -v error -show_entries format=duration,size \
  -show_entries stream=codec_name,codec_type,width,height \
  -of default=nw=1 <out-dir>/narrated.mp4
```

Then open `studio_url` from the result JSON in YouTube Studio, verify the draft
is private with correct title/description, and flip it to public. Per-workflow
validation (e.g. the url-ad offline gate + CLI checks) lives in each workflow doc.
</validation>
