# Workflow: idea-video

The original unattended "idea -> private YouTube draft" flow. Routed from
`SKILL.md` Step 0 when the request is idea/topic/Studio-inspiration seeded (not a
URL, not an existing product's real UI). Shares the building blocks and contracts
documented in `SKILL.md` (`<shared>`, `<gates>`, `<requirements>`,
`<important_constraints>`, `<files>`).

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

Every stage must pass before the next begins. Exit-code-0 and `{"ok": true}` are
necessary but NOT sufficient: after each stage the orchestrator runs a
`scripts/stage_gates.py` verification on the REAL artifact and hard-stops
(`GATE FAILED after '<stage>'`) the moment something is missing or degraded — a
truncated/streamless video, a SILENT narration track (TTS produced nothing), an
empty ideas file, or a storyboard with no rendered frames. A failing gate never
reaches the next stage and never uploads. See `<gates>` in `SKILL.md`.

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
   (forces a libx264 re-encode). Captions are sized to the REAL video frame and
   tuned per FORMAT — Shorts/vertical (9:16) get a phone-legible font and a tall
   bottom margin that clears the Shorts UI; a standard/landscape (16:9) video
   keeps the proven smaller look. `subtitles._ass_header` sets `PlayResX/Y` to
   the actual frame (1:1 scaling) and branches on portrait vs landscape, so a
   fixed-aspect header never balloons or overflows the text. Styling is
   Korean-variety/TV-show flavored: captions cycle a colour+position palette
   (`_CAPTION_PRESETS`) and POP key words (accent colour + bigger, bolder,
   scale-animated) — emphasis terms come from `script.json` youtube tags (else
   each caption pops its longest token), capped so a line never becomes a wall
   of colour. BGM resolution order is explicit `--bgm` >
   mood cache > Jamendo. Real generation is the default: if no REAL source
   resolves, the stage HARD-STOPS unless `--allow-synth-bgm` is passed, which
   permits the synthesized CC0 ambient pad (ffmpeg `lavfi`) fallback; `--no-bgm`
   is the explicit narration-only opt-out. Only CC-BY/CC-BY-SA/CC0
   tracks are accepted; when a track requires credit, attribution is written to
   `CREDITS.txt` beside the video and threaded into the upload description.
   `--no-bgm`/`--no-subtitles` restore the prior single-shot, music-free path.
   The final mux FREEZE-PADS the video (holds the last frame via ffmpeg `tpad`)
   up to the narration length, so a clip shorter than the voiceover (an ~8s Flow
   clip vs a ~15s narration) is never truncated mid-sentence; the output length
   equals the narration. The pad is applied BEFORE the caption burn so cues over
   the held tail still render. (For motion across the whole runtime instead of a
   held tail, generate one clip per scene and `assemble_flow_video.py` stretches
   them to the narration with `setpts`.)
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
in YouTube Studio and verify it remains private. Public release is a separate user action.
</process>
