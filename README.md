# vimax-youtube-autopilot

**Idea to private YouTube draft, with one command.** An unattended pipeline that
harvests a trending idea, storyboards it, renders motion clips with Google Flow,
removes the watermark, narrates it in Korean, lays low-volume royalty-free music
and burned-in captions under it, and uploads it as a **private** draft. The only
human step left is flipping that draft to public.

```
Studio inspiration  ->  codex storyboard  ->  Google Flow video  ->  delogo
                    ->  Supertonic Korean TTS + ducked BGM + captions
                    ->  private YouTube draft
```

> Status: proven end-to-end on a live channel (2026-06-03) — real Flow render
> (3 scenes, Gemini Omni), delogo, Supertonic narration, ducked royalty-free
> BGM, burned key-sentence captions, and a private Studio draft upload, all
> unattended.

---

## Why

Short-form video production is a chain of tedious, tool-switching steps: find an
idea, break it into scenes, generate visuals, clean them up, write and record
narration, add music and captions, then fight an upload UI. This project
automates the entire chain as a set of small, composable CLIs. Each stage runs
standalone with the same contract, or all seven run from one orchestrator.

It is built to be **safe by default**: nothing is published without an explicit
opt-in (the upload defaults to a private draft), no secrets are hardcoded, and a
`--dry-run` validates the whole chain without spending Flow credits or touching
your channel.

## The pipeline

Seven stages, chained by `scripts/auto_youtube_pipeline.py`. Each stage is a
standalone CLI that prints exactly one `{"ok": true, ...}` JSON line on stdout
and logs to stderr. After every stage the orchestrator re-inspects the produced
artifact through `stage_gates.py` and **hard-stops on any degradation**, so a
failed render or mux never carries forward or uploads.

| # | Stage | Script | What it does |
|---|-------|--------|--------------|
| 1 | Harvest | `harvest_ideas.py` | Scrape the YouTube Studio inspiration feed (fallback: youtube.com trending), rank ideas with codex. `--topic` skips scraping and synthesizes ideas directly. |
| 2 | Storyboard | `make_storyboard.py` | Expand the chosen idea into an N-scene JSON breakdown, render one storyboard PNG per scene via the gpt-image-2 skill. |
| 3 | Script | `write_script.py` | codex writes the Korean narration, a Flow prompt, per-scene prompts, key sentences for captions, and YouTube metadata (title/description/tags/category). |
| 4 | Video | `generate_video.py` | Render and download one Flow clip per scene, then `assemble_flow_video.py` concats, delogos, fits to narration length, and muxes. |
| 5 | Delogo | `remove_logo.py` | ffmpeg `delogo` wipes the bottom-right Gemini/Flow sparkle watermark. |
| 6 | Narration + music + captions | `add_narration.py` | Supertonic Korean TTS (default voice F1/Mina) synthesizes the voice sentence by sentence, lays a ducked low-volume royalty-free BGM bed under it, and burns format-aware key-sentence captions. See [Stage 6 in depth](#stage-6-in-depth-narration-music-captions). |
| 7 | Upload | `upload_youtube_studio.py` / `upload_youtube.py` | Upload as a **private** draft, either by driving the logged-in Studio browser (no OAuth) or via the YouTube Data API v3. |

The pipeline **stops** after the upload. The only remaining human step is to open
the private draft in YouTube Studio and flip it private -> public once reviewed.

## Quick start

Run the whole pipeline and stop at the private draft. The proven, OAuth-free path
uploads by driving the logged-in Studio browser (no `--client-secret` needed):

```bash
python3 scripts/auto_youtube_pipeline.py \
  --topic "" \
  --idea-index 0 \
  --scenes 6
```

Topic-seeded run (skip scraping, synthesize ideas around a topic):

```bash
python3 scripts/auto_youtube_pipeline.py \
  --topic "초보자를 위한 홈카페 레시피"
```

Narration-only (no music, no captions):

```bash
python3 scripts/auto_youtube_pipeline.py \
  --topic "테스트 주제" --no-bgm --no-subtitles
```

Validate the full chain **without** spending Flow credits or uploading.
`--allow-synth-bgm` lets Stage 6 use the synthesized pad so the run does not
hard-stop when no `JAMENDO_CLIENT_ID` or BGM cache is present:

```bash
python3 scripts/auto_youtube_pipeline.py \
  --topic "테스트 주제" --dry-run --video ./sample.mp4 --allow-synth-bgm
```

On success the orchestrator prints exactly one JSON line:

```json
{"ok": true, "manifest": "<path>", "studio_url": "<url|null>", "stopped_for": "human-publish"}
```

## Stage 6 in depth: narration, music, captions

Stage 6 (`add_narration.py`) is three cohesive sibling modules behind one CLI:

- **Narration** — Supertonic Korean TTS synthesizes the voice **one sentence at a
  time**, ffprobes each clip for drift-free timing, and concatenates them. The
  final mux **freeze-pads** the video (holds the last frame) up to the narration
  length, so an ~8s Flow clip under a ~15s voiceover is never truncated
  mid-sentence; output length equals the narration.
- **Music** (`bgm_library.py` + `audio_mix.py`) — a low-volume (~0.16)
  royalty-free track is laid under the voice with `afade` in/out and sidechain
  **ducking** (on by default). Resolution order is explicit `--bgm` > mood cache
  > Jamendo. **Real generation is the default**: if no real source resolves the
  stage hard-stops unless `--allow-synth-bgm` permits the synthesized CC0 ambient
  pad. Only CC-BY / CC-BY-SA / CC0 tracks are accepted; required credit is written
  to `CREDITS.txt` and threaded into the upload description. `--no-bgm` opts out.
- **Captions** (`subtitles.py`) — only the **key** sentences (from `script.json`
  `key_sentences`, else a sparse heuristic) are burned in at exact times. Captions
  are **format-aware**: Shorts/vertical (9:16) get a phone-legible font and a tall
  bottom margin that clears the Shorts UI; standard/landscape (16:9) keeps the
  proven smaller look. Styling is Korean-variety-show flavored — a colour+position
  palette with key words popped (accent colour, bigger, bolder). `--no-subtitles`
  opts out. Sidecar `captions.srt` / `captions.ass` are written beside the video.

## Product-ad mode

Advertising an existing product (an app, site, or device with a real UI) adds one
rule: the product's real screens must appear **faithfully**. Feeding a real UI
screenshot through Flow garbles its text and layout, so the timeline goes
**hybrid**:

- **Flow renders only B-roll** (people, hands, environment, mood) — never the
  product UI itself.
- **Real product screens** are captured from the live product (or supplied) and
  shown verbatim as Ken-Burns motion clips via `build_kenburns_clip.py` (sharp
  pixels, subtle pan, blurred-cover background). They are never sent to a
  generative model.
- Both clip kinds are normalized to one geometry and concatenated with
  `assemble_flow_video.py`; narration, BGM, captions, and upload then proceed
  unchanged.

Net effect: the audience sees the genuine product UI, while Flow supplies only the
cinematic surround.

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
  (pillow, google-api-python-client, google-auth-oauthlib, google-auth-httplib2).
  Stage 6 BGM + captions add **no new pip deps** — they use the stdlib plus
  external CLIs.
- **ffmpeg** and **ffprobe** on PATH, built with **libass** (caption burn) and
  `sidechaincompress` / `afade` / `amix` (delogo, mux, BGM ducking, duration,
  dry-run placeholder).
- **codex CLI** logged in via ChatGPT (`codex login status` => "Logged in using
  ChatGPT"); needs the `image_generation` entitlement for storyboards.
- **Chrome** with remote debugging, logged into the target Google account with
  access to **both** YouTube Studio and Google Flow.
- **Node 18.3+** and npm for Supertonic TTS and the Playwright agent CLI.
- *(Optional)* **`JAMENDO_CLIENT_ID`** env var to pull fresh royalty-free BGM from
  Jamendo; without it, BGM falls back to the mood cache or (with
  `--allow-synth-bgm`) a synthesized pad. Never hardcoded.
- *(Data API upload path only)* A **YouTube OAuth Desktop-app client secret** JSON
  (passed via `--client-secret`, never hardcoded). One-time bootstrap:
  `scripts/get_youtube_token.py`. Token cache default:
  `~/.config/vimax-youtube-autopilot/token.json`. The Studio-browser upload path
  needs none of this.

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

The live browser stages spend credits and are hard to reverse, so the agent
harness is expected to gate the attach behind an explicit human approval — grant a
standing allow for `npx @playwright/cli@latest *`, or approve each stage. Never
work around the gate.

## CLI reference

Flags on `auto_youtube_pipeline.py`:

| Flag | Default | Purpose |
|------|---------|---------|
| `--topic` | `""` | Synthesize ideas around this topic instead of scraping. |
| `--idea-index` | `0` | 0-based idea to use from the harvest. |
| `--scenes` | `6` | Storyboard scene count. |
| `--duration` | `8` | Seconds per scene/clip. |
| `--aspect-ratio` | `16:9` | Output aspect ratio (use `9:16` for Shorts). |
| `--voice` | `F1` | Supertonic voice id (F1/Mina). |
| `--no-bgm` | off | Stage 6: disable background music. |
| `--bgm` | — | Stage 6: explicit BGM track path (overrides mood resolution). |
| `--allow-synth-bgm` | off | Stage 6: permit the synthesized CC0 pad when no real BGM resolves (else hard-stop). |
| `--no-subtitles` | off | Stage 6: disable burned key-sentence captions. |
| `--privacy` | `private` | Upload visibility: `private` / `unlisted` / `public`. Default keeps a private draft. |
| `--dry-run` | off | Skip Flow submit and real upload. |
| `--no-upload` | off | Stop before upload; keep the final video local. |
| `--out-dir` | run dir | Run output directory. |
| `--flow-project-url` | preset | Google Flow project URL. |
| `--channel-url` | preset | Studio inspiration feed URL. |
| `--client-secret` | — | OAuth client secret JSON path for the Data API upload. |
| `--token` | — | Token cache path for the Data API upload. |
| `--session` | `vya` | Single Playwright agent session for all browser stages. |
| `--no-attach` | off | Reuse an already-attached browser session. |
| `--skip-harvest` / `--ideas-json` | — | Reuse an existing ideas file. |
| `--skip-storyboard` | off | Reuse an existing storyboard dir. |
| `--skip-video` / `--video` | — | Reuse a supplied MP4 as the raw video. |

## Validation

Confirm the orchestrator and every stage parse cleanly, then run the test suite:

```bash
for f in scripts/*.py; do python3 "$f" --help >/dev/null || echo "FAIL: $f"; done
python3 -m pytest tests/ -q
```

Validate the full chain without Flow credits or an upload, then inspect the run:

```bash
python3 scripts/auto_youtube_pipeline.py --topic "테스트" --dry-run --allow-synth-bgm
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
  stage_gates.py             per-stage output verification; hard-stop on degradation
  harvest_ideas.py           Stage 1: inspiration / trending -> ranked ideas
  make_storyboard.py         Stage 2: idea -> scene beats + storyboard PNGs
  write_script.py            Stage 3: Korean narration + Flow prompts + metadata
  generate_video.py          Stage 4: Flow render via google_flow_cli.py
  assemble_flow_video.py     concat scene clips + delogo + fit + mux
  build_kenburns_clip.py     product-ad mode: real screen -> Ken-Burns motion clip
  build_slideshow.py         Flow-free fallback: narrated Ken-Burns slideshow
  remove_logo.py             Stage 5: ffmpeg delogo watermark removal
  add_narration.py           Stage 6: Supertonic TTS + ducked BGM + captions + mux
  subtitles.py               Stage 6: key-sentence segmentation, timing, .srt/.ass
  bgm_library.py             Stage 6: resolve one royalty-free track by mood
  audio_mix.py               Stage 6: pure ffmpeg voice+BGM duck/mix graph
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
  test_subtitles.py          caption split, timing, key selection, sidecar files
  test_bgm_library.py        BGM resolution order + license labeling
  test_audio_mix.py          voice+BGM duck/mix graph
  test_stage_gates.py        per-stage artifact gate checks
  test_pipeline_gates.py     orchestrator gate wiring
  test_add_narration_integration.py  end-to-end Stage 6 (real ffmpeg)
  test_write_script.py       script + metadata shape
  test_flow_src.py           Flow clip source selection
```

## Safety and constraints

- Upload visibility **defaults to a private draft** (`--privacy private`) and the
  pipeline stops there — it only uploads as `unlisted`/`public` if you explicitly
  pass `--privacy`. It never flips an existing draft.
- Each fresh Flow submit and each codex call may spend credits/tokens — prefer
  `--dry-run` to validate the chain first.
- BGM is **royalty-free only** (CC-BY / CC-BY-SA / CC0); required attribution is
  written to `CREDITS.txt` and threaded into the upload description. With BGM on
  and no real source, the stage hard-stops rather than silently degrading.
- Secrets (OAuth client secret, token, `JAMENDO_CLIENT_ID`) come only from CLI
  args / env / files; nothing is hardcoded, and the uploader never prints
  token/secret contents.
- Studio uses Shadow DOM + virtualized lists and Flow's DOM drifts; the scraper
  pierces shadow roots, scrolls, and falls back to youtube.com trending.
- When a selector breaks or generated quality drifts, update the relevant
  selector/prompt and append a dated entry to `references/improvement_log.md`.
  `references/runbook.md` has per-stage debug checklists.

## License

Private project. All rights reserved unless stated otherwise.
