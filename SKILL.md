---
name: vimax-youtube-autopilot
description: Fully-automated YouTube video pipeline. Harvests trending ideas from the YouTube Studio inspiration feed (fallback YouTube trending), expands a chosen idea into a codex storyboard, renders the clip with Gemini/Google Flow, removes the Flow watermark with ffmpeg delogo, narrates it in Korean with Supertonic TTS, and uploads it as a PRIVATE draft via the YouTube Data API. Everything runs unattended; the ONLY human step is flipping the private draft to public in YouTube Studio. Use when the user wants an end-to-end "idea to private YouTube draft" automation, a Studio-inspired short, or a reproducible Flow + Korean-narration upload pipeline.
---

<objective>
Take a channel from inspiration to a ready-to-publish private YouTube draft with
one command, via this required chain:
Studio inspiration ideas -> codex storyboard -> Gemini/Flow video ->
delogo watermark removal -> Supertonic Korean TTS narration ->
private YouTube Data API upload (stops at the human publish gate).
</objective>

<when_to_use>
- The user wants an unattended "idea to private draft" YouTube workflow.
- The user wants a short inspired by their channel's Studio inspiration feed.
- The user wants a Google Flow clip with Korean narration uploaded as a private
  YouTube draft for review before publishing.
- The user wants to re-run a single stage (harvest, storyboard, script, video,
  delogo, narration, upload) with the same contracts.
</when_to_use>

<quick_start>
One command runs the whole pipeline and stops at the private draft:

```bash
python3 scripts/auto_youtube_pipeline.py \
  --topic "" \
  --idea-index 0 \
  --scenes 6 \
  --client-secret /path/to/oauth_client_secret.json
```

Topic-seeded run (skip scraping; synthesize ideas around a topic):

```bash
python3 scripts/auto_youtube_pipeline.py \
  --topic "초보자를 위한 홈카페 레시피" \
  --client-secret /path/to/oauth_client_secret.json
```

Validate the whole pipeline WITHOUT spending Flow credits or uploading:

```bash
python3 scripts/auto_youtube_pipeline.py \
  --topic "테스트 주제" --dry-run --video ./sample.mp4
```

On success the orchestrator prints exactly one JSON line:
`{"ok": true, "manifest": "<path>", "studio_url": "<url|null>", "stopped_for": "human-publish"}`.
All per-stage progress goes to stderr.
</quick_start>

<process>
The orchestrator `scripts/auto_youtube_pipeline.py` chains seven stage scripts as
subprocesses, threading each stage's output into the next and writing a
`manifest.json`. Each stage also runs standalone with the same contract (one
`{"ok": true, ...}` JSON line on stdout, logs on stderr).

1. **Harvest** (`harvest_ideas.py`): attach to logged-in Chrome, scrape the
   YouTube Studio inspiration feed (`js/studio_inspiration.js`), fall back to
   youtube.com trending, then ask codex to rank N idea objects. With `--topic`
   it skips scraping and synthesizes ideas directly. Output: `ideas.json`.
2. **Storyboard** (`make_storyboard.py`): pick the idea (`--idea-index`), ask
   codex for an N-scene JSON breakdown, render one storyboard PNG per scene via
   the gpt-image-2 skill's `gen.sh`. Output: `storyboard/` + `storyboard.json`.
3. **Script** (`write_script.py`): codex writes the Korean narration, a
   consolidated Flow prompt, per-scene prompts, and YouTube metadata
   (title/description/tags/category) as strict JSON. Output: `script.json`.
4. **Video** (`generate_video.py`): seed the vendored `google_flow_cli.py` with
   the Flow prompt + up to 3 storyboard frames, render and download ONLY the new
   post-submit MP4. Output: `raw_flow.mp4`. In `--dry-run` this is replaced by a
   supplied `--video` or a generated 2s placeholder clip.
5. **Delogo** (`remove_logo.py`): ffmpeg `delogo` wipes the bottom-right
   Gemini/Flow watermark; the box is auto-sized from the frame resolution.
   Output: `delogo.mp4`.
6. **Narration** (`add_narration.py`): Supertonic Korean TTS (default F1/Mina,
   speed 0.95, steps 16, lang ko) synthesizes the voice and ffmpeg muxes it.
   Output: `narrated.mp4`.
7. **Upload** (`upload_youtube.py`): YouTube Data API v3 resumable upload as a
   PRIVATE draft, metadata from `script.json`. Output: `video_id` + `studio_url`
   in `manifest.json`. In `--dry-run` it validates only and uploads nothing.

The pipeline STOPS here. The ONLY remaining human step: open the private draft
in YouTube Studio and flip it private -> public once reviewed.
</process>

<requirements>
- Python 3.12 with `pip install -r requirements.txt` (google-api-python-client,
  google-auth-oauthlib, google-auth-httplib2, pillow).
- `ffmpeg` and `ffprobe` on PATH (delogo, mux, duration, dry-run placeholder).
- `codex` CLI logged in via ChatGPT (`codex login status` => "Logged in using
  ChatGPT"); needs the `image_generation` entitlement for storyboards.
- Chrome with remote debugging, logged into the target Google account with
  access to BOTH YouTube Studio and Google Flow; the Playwright agent CLI
  attaches over CDP endpoint `chrome`.
- Node 18.3+ and npm for the Supertonic fallback and the Playwright agent CLI.
- A YouTube OAuth Desktop-app client secret JSON (passed via `--client-secret`,
  never hardcoded). One-time bootstrap: `scripts/get_youtube_token.py`. Token
  cache default: `~/.config/vimax-youtube-autopilot/token.json`.
</requirements>

<important_constraints>
- Upload privacy defaults to `private`. The pipeline NEVER auto-publishes; the
  only human step is flipping the draft to public in YouTube Studio.
- Each fresh Flow submit and each codex call may spend credits/tokens; prefer
  `--dry-run` to validate the chain before a real run.
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
- `scripts/auto_youtube_pipeline.py` — one-command end-to-end orchestrator;
  writes `manifest.json` and stops at the private draft.
- `scripts/harvest_ideas.py` — Stage 1: Studio inspiration / trending -> ranked
  ideas via codex.
- `scripts/make_storyboard.py` — Stage 2: idea -> scene beats + storyboard PNGs.
- `scripts/write_script.py` — Stage 3: Korean narration + Flow prompts + YouTube
  metadata.
- `scripts/generate_video.py` — Stage 4: Flow render via `google_flow_cli.py`.
- `scripts/remove_logo.py` — Stage 5: ffmpeg `delogo` watermark removal.
- `scripts/add_narration.py` — Stage 6: Supertonic Korean TTS + ffmpeg mux.
- `scripts/upload_youtube.py` — Stage 7: private YouTube Data API upload.
- `scripts/get_youtube_token.py` — one-time OAuth consent + token cache.
- `scripts/google_flow_cli.py` — vendored Flow browser-automation CLI.
- `scripts/js/` — browser helpers (`studio_inspiration.js`, `flow_*.js`).
- `references/runbook.md` — per-stage operational + debug guide.
- `references/improvement_log.md` — living log of selector/prompt/failure fixes.
- `tests/test_remove_logo.py` — delogo box geometry unit tests.
</files>

<validation>
Confirm the orchestrator and every stage parse cleanly:

```bash
for f in scripts/*.py; do python3 "$f" --help >/dev/null || echo "FAIL: $f"; done
python3 -m pytest tests/test_remove_logo.py -q
```

Validate the full chain without Flow credits or an upload (uses a 2s placeholder
clip when no `--video` is supplied) and inspect the manifest:

```bash
python3 scripts/auto_youtube_pipeline.py --topic "테스트" --dry-run
cat <out-dir>/manifest.json
```

After a real run, confirm the final MP4 and the private draft:

```bash
ffprobe -v error -show_entries format=duration,size \
  -show_entries stream=codec_name,codec_type,width,height \
  -of default=nw=1 <out-dir>/narrated.mp4
```

Then open `studio_url` from the result JSON in YouTube Studio, verify the draft
is private with correct title/description, and flip it to public.
</validation>
