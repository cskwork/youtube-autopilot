---
name: vimax-youtube-autopilot
description: Fully-automated YouTube video pipeline. Harvests trending ideas from the YouTube Studio inspiration feed (fallback YouTube trending), expands a chosen idea into a codex storyboard, renders motion clips with Gemini/Google Flow (one per scene, then assembled), removes the Flow sparkle watermark with ffmpeg delogo, narrates it in Korean with Supertonic TTS, and uploads it as a PRIVATE draft. Everything runs unattended; the ONLY human step is flipping the private draft to public in YouTube Studio. Two proven fallbacks for account/access splits: when the channel account lacks Flow access, build_slideshow.py renders a narrated Ken-Burns video from the storyboard stills; when the channel account differs from any GCP project (so Data API OAuth is impractical), upload_youtube_studio.py uploads by driving the logged-in Studio browser instead. Use when the user wants an end-to-end "idea to private YouTube draft" automation, a Studio-inspired short, or a reproducible Flow + Korean-narration upload pipeline.
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

<browser_attach>
The browser stages (harvest, Flow video, Studio upload) drive ONE logged-in
Chrome session via the Playwright agent CLI. Proven setup (Chrome 148, macOS):

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
</browser_attach>

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
   a Flow prompt + storyboard frames, render and download ONLY the new
   post-submit MP4. For a full-length result, call it once per
   `scene_prompts[i]` (each seeded with its own `scene_0i.png`) to get one ~8s
   clip per scene, then `assemble_flow_video.py` concats them, delogos, fits to
   the narration length, and muxes. In `--dry-run` this is a supplied `--video`
   or a generated 2s placeholder.
   - Flow access fallback: if the channel account has no Flow video access, skip
     Flow entirely and run `build_slideshow.py` to render a narrated Ken-Burns
     video from the storyboard stills (no credits, no browser).
5. **Delogo** (`remove_logo.py`): ffmpeg `delogo` wipes the bottom-right
   Gemini/Flow sparkle watermark. Default box auto-sizes from resolution; for
   1280x720 Flow clips the watermark sits at ~(1140,645), so `--box
   1095:600:160:100` is a tight fit. (`assemble_flow_video.py` does this inline.)
   Output: `delogo.mp4`.
6. **Narration + music + captions** (`add_narration.py`): Supertonic Korean TTS
   (default F1/Mina, speed 0.95, steps 16, lang ko) synthesizes the voice
   ONE SENTENCE AT A TIME, ffprobes each duration for drift-free timing, and
   concatenates them into the full narration WAV. A low-volume (~0.16)
   royalty-free background track is laid under it with `afade` in/out and
   sidechain DUCKING (on by default), via three cohesive sibling modules:
   `subtitles.py` (segmentation + per-sentence timing + `.srt`/`.ass`),
   `bgm_library.py` (resolve one track by mood), `audio_mix.py` (pure ffmpeg
   mix graph). Only the KEY sentences (from `script.json` `key_sentences`, else
   a sparse heuristic) are burned in as bottom-centered captions at exact times
   (forces a libx264 re-encode). BGM is ALWAYS present: if the optional
   `JAMENDO_CLIENT_ID` env key is unset or the network/track is unusable, a
   synthesized ambient pad (CC0, ffmpeg `lavfi`) is used. Only CC-BY/CC-BY-SA/CC0
   tracks are accepted; when a track requires credit, attribution is written to
   `CREDITS.txt` beside the video and threaded into the upload description.
   `--no-bgm`/`--no-subtitles` restore the prior single-shot, music-free path.
   Output: `narrated.mp4` (+ `captions.srt`/`captions.ass`, optional `CREDITS.txt`).
7. **Upload** — two paths, same private-draft outcome:
   - `upload_youtube.py`: YouTube Data API v3 resumable upload, metadata from
     `script.json`. Needs an OAuth Desktop client whose consent screen lists the
     channel account as a test user. In `--dry-run` it validates only.
   - `upload_youtube_studio.py` (proven, no OAuth): drives the logged-in Studio
     browser — `setInputFiles` the MP4, set title/description, mark
     not-made-for-kids, advance the wizard, set visibility, save. Use this when
     the channel account differs from the GCP project account (the common case).

The pipeline STOPS here. The ONLY remaining human step: open the private draft
in YouTube Studio and flip it private -> public once reviewed.
</process>

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
- `scripts/generate_video.py` — Stage 4: Flow render via `google_flow_cli.py`
  (call once per scene for a full-length video).
- `scripts/assemble_flow_video.py` — concat scene clips + delogo + fit to
  narration + mux into one MP4.
- `scripts/build_slideshow.py` — Flow-free fallback: narrated Ken-Burns video
  from the storyboard stills.
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
  TTS, real ffmpeg): asserts audio stream, duration, captions, CREDITS handling.
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
