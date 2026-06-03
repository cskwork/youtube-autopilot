# vimax-youtube-autopilot

**Idea to private YouTube draft, with one command.** An unattended pipeline that
harvests a trending idea, storyboards it, renders motion clips with Google Flow,
removes the watermark, narrates it in Korean, and uploads it as a **private**
draft. The only human step left is flipping that draft to public.

```
Studio inspiration  ->  codex storyboard  ->  Google Flow video  ->  delogo
                    ->  Supertonic Korean TTS  ->  private YouTube draft
```

> Status: proven end-to-end on a live channel (2026-06-03) — real Flow render
> (3 scenes, Gemini Omni), delogo, Supertonic narration, and a private Studio
> draft upload, all unattended.

---

## Why

Short-form video production is a chain of tedious, tool-switching steps: find an
idea, break it into scenes, generate visuals, clean them up, write and record
narration, then fight an upload UI. This project automates the entire chain as a
set of small, composable CLIs. Each stage runs standalone with the same
contract, or all seven run from one orchestrator.

It is built to be **safe by default**: nothing is auto-published, no secrets are
hardcoded, and a `--dry-run` validates the whole chain without spending Flow
credits or touching your channel.

## The pipeline

Seven stages, chained by `scripts/auto_youtube_pipeline.py`. Each stage is a
standalone CLI that prints exactly one `{"ok": true, ...}` JSON line on stdout
and logs to stderr.

| # | Stage | Script | What it does |
|---|-------|--------|--------------|
| 1 | Harvest | `harvest_ideas.py` | Scrape the YouTube Studio inspiration feed (fallback: youtube.com trending), rank ideas with codex. `--topic` skips scraping and synthesizes ideas directly. |
| 2 | Storyboard | `make_storyboard.py` | Expand the chosen idea into an N-scene JSON breakdown, render one storyboard PNG per scene via the gpt-image-2 skill. |
| 3 | Script | `write_script.py` | codex writes the Korean narration, a Flow prompt, per-scene prompts, and YouTube metadata (title/description/tags/category). |
| 4 | Video | `generate_video.py` | Render and download one Flow clip per scene, then `assemble_flow_video.py` concats, delogos, fits to narration length, and muxes. |
| 5 | Delogo | `remove_logo.py` | ffmpeg `delogo` wipes the bottom-right Gemini/Flow sparkle watermark. |
| 6 | Narration | `add_narration.py` | Supertonic Korean TTS (default voice F1/Mina) synthesizes the voice and ffmpeg muxes it. |
| 7 | Upload | `upload_youtube_studio.py` / `upload_youtube.py` | Upload as a **private** draft, either by driving the logged-in Studio browser (no OAuth) or via the YouTube Data API v3. |

The pipeline **stops** after the upload. The only remaining human step is to open
the private draft in YouTube Studio and flip it private -> public once reviewed.

## Quick start

Run the whole pipeline and stop at the private draft:

```bash
python3 scripts/auto_youtube_pipeline.py \
  --topic "" \
  --idea-index 0 \
  --scenes 6 \
  --client-secret /path/to/oauth_client_secret.json
```

Topic-seeded run (skip scraping, synthesize ideas around a topic):

```bash
python3 scripts/auto_youtube_pipeline.py \
  --topic "초보자를 위한 홈카페 레시피" \
  --client-secret /path/to/oauth_client_secret.json
```

Validate the full chain **without** spending Flow credits or uploading:

```bash
python3 scripts/auto_youtube_pipeline.py \
  --topic "테스트 주제" --dry-run --video ./sample.mp4
```

On success the orchestrator prints exactly one JSON line:

```json
{"ok": true, "manifest": "<path>", "studio_url": "<url|null>", "stopped_for": "human-publish"}
```

## Built-in fallbacks

Real channels rarely have every account and entitlement on one login. Two proven
fallbacks handle the common splits:

- **No Flow access on the channel account** — skip Flow entirely.
  `build_slideshow.py` renders a narrated Ken-Burns video from the storyboard
  stills. No credits, no browser.
- **Channel account differs from the GCP project** (so Data API OAuth is
  impractical) — `upload_youtube_studio.py` uploads by driving the logged-in
  Studio browser instead of the API. This is the proven, OAuth-free path.

## Requirements

- **Python 3.12** with `pip install -r requirements.txt`
  (google-api-python-client, google-auth-oauthlib, google-auth-httplib2, pillow).
- **ffmpeg** and **ffprobe** on PATH (delogo, mux, duration, dry-run placeholder).
- **codex CLI** logged in via ChatGPT (`codex login status` => "Logged in using
  ChatGPT"); needs the `image_generation` entitlement for storyboards.
- **Chrome** with remote debugging, logged into the target Google account with
  access to **both** YouTube Studio and Google Flow.
- **Node 18.3+** and npm for Supertonic TTS and the Playwright agent CLI.
- A **YouTube OAuth Desktop-app client secret** JSON (passed via
  `--client-secret`, never hardcoded). One-time bootstrap:
  `scripts/get_youtube_token.py`. Token cache default:
  `~/.config/vimax-youtube-autopilot/token.json`.

## Browser attach (the hard-won part)

The browser stages (harvest, Flow video, Studio upload) drive **one** logged-in
Chrome session via the Playwright agent CLI. Proven setup (Chrome 148, macOS):

1. Chrome 148 ignores `--remote-debugging-port` on the default profile. Enable it
   via the UI instead: open `chrome://inspect/#remote-debugging` and turn on
   "Allow remote debugging for this browser instance" (serves 127.0.0.1:9222).
2. Attach once: `npx @playwright/cli@latest attach --cdp=chrome -s=vya`.
3. Reuse that one session for every stage (`--session vya --no-attach`).
4. **Always use the system npm cache** (empty `--npm-cache`). A custom cache
   pulls a different CLI version whose daemon cannot see the attached session —
   the #1 silent failure (scrapes return parse errors).
5. `run-code` runs `page => ...` in NODE context; DOM scraping must live inside
   `page.evaluate(() => {...})`.

## CLI reference

Core flags on `auto_youtube_pipeline.py`:

| Flag | Default | Purpose |
|------|---------|---------|
| `--topic` | `""` | Synthesize ideas around this topic instead of scraping. |
| `--idea-index` | `0` | 0-based idea to use from the harvest. |
| `--scenes` | `6` | Storyboard scene count. |
| `--duration` | `8` | Seconds per scene/clip. |
| `--aspect-ratio` | `16:9` | Output aspect ratio. |
| `--voice` | `F1` | Supertonic voice id (F1/Mina). |
| `--dry-run` | off | Skip Flow submit and real upload. |
| `--no-upload` | off | Stop before upload; keep the final video local. |
| `--client-secret` | — | OAuth client secret JSON path for the Data API upload. |
| `--session` | `vya` | Single Playwright agent session for all browser stages. |
| `--skip-harvest` / `--ideas-json` | — | Reuse an existing ideas file. |
| `--skip-storyboard` | off | Reuse an existing storyboard dir. |
| `--skip-video` / `--video` | — | Reuse a supplied MP4 as the raw video. |

## Validation

Confirm the orchestrator and every stage parse cleanly:

```bash
for f in scripts/*.py; do python3 "$f" --help >/dev/null || echo "FAIL: $f"; done
python3 -m pytest tests/test_remove_logo.py -q
```

Validate the full chain without Flow credits or an upload, then inspect the run:

```bash
python3 scripts/auto_youtube_pipeline.py --topic "테스트" --dry-run
cat <out-dir>/manifest.json
```

After a real run, confirm the final MP4 before flipping the draft public:

```bash
ffprobe -v error -show_entries format=duration,size \
  -show_entries stream=codec_name,codec_type,width,height \
  -of default=nw=1 <out-dir>/narrated.mp4
```

## Project layout

```
scripts/
  auto_youtube_pipeline.py   one-command orchestrator; writes manifest.json
  harvest_ideas.py           Stage 1: inspiration / trending -> ranked ideas
  make_storyboard.py         Stage 2: idea -> scene beats + storyboard PNGs
  write_script.py            Stage 3: Korean narration + Flow prompts + metadata
  generate_video.py          Stage 4: Flow render via google_flow_cli.py
  assemble_flow_video.py     concat scene clips + delogo + fit + mux
  build_slideshow.py         Flow-free fallback: narrated Ken-Burns slideshow
  remove_logo.py             Stage 5: ffmpeg delogo watermark removal
  add_narration.py           Stage 6: Supertonic Korean TTS + mux
  upload_youtube.py          Stage 7a: private YouTube Data API upload
  upload_youtube_studio.py   Stage 7b: private upload by driving Studio (no OAuth)
  get_youtube_token.py       one-time OAuth consent + token cache
  google_flow_cli.py         vendored Flow browser-automation CLI
  js/                        browser helpers (studio_inspiration, flow_*, studio_upload)
references/
  runbook.md                 per-stage operational + debug guide
  improvement_log.md         living log of selector/prompt/failure fixes
tests/
  test_remove_logo.py        delogo box geometry unit tests
```

## Safety and constraints

- Upload privacy defaults to **private**. The pipeline **never** auto-publishes.
- Each fresh Flow submit and each codex call may spend credits/tokens — prefer
  `--dry-run` to validate the chain first.
- Secrets (OAuth client secret, token) come only from CLI args / files; nothing
  is hardcoded, and the uploader never prints token/secret contents.
- Studio uses Shadow DOM + virtualized lists and Flow's DOM drifts; the scraper
  pierces shadow roots, scrolls, and falls back to youtube.com trending.
- When a selector breaks or generated quality drifts, update the relevant
  selector/prompt and append a dated entry to `references/improvement_log.md`.
  `references/runbook.md` has per-stage debug checklists.

## License

Private project. All rights reserved unless stated otherwise.
