# ViMax YouTube Autopilot — Improvement Log

A living log. This skill drives third-party UIs (YouTube Studio, Google Flow)
whose DOM and behavior drift over time, plus generative models whose prompts
need ongoing tuning. Append a dated entry every time you fix a selector, tune a
prompt, or hit a new failure mode. Newest entries on top within each section.

Entry format: `- YYYY-MM-DD — what changed / what was observed — why / impact`.

---

## Selectors / DOM changes

Track scraper and automation selector changes for Studio inspiration, youtube.com
trending fallback, and Flow compose/status/download. Note which selector broke,
what replaced it, and the date the live DOM was confirmed.

- 2026-06-03 — `studio_inspiration.js` rewritten to run inside `page.evaluate(() => {...})` — `run-code` executes `page => ...` in NODE context, so the original browser-API code threw "setTimeout/document is not defined". Confirmed live on the Studio inspiration feed.
- 2026-06-03 — Flow video mode confirmed via the prompt-bar model selector: open it (label "Nano Banana 2"/이미지), pick the `동영상` (play_circle) option; selector then reads "동영상 · 8s crop_16_9 x2". `flow_compose.tmpl.js` `ensureVideoMode` matches this.
- 2026-06-03 — Studio upload dialog reached at `…/videos/upload?d=ud`; title box `#title-textarea #textbox`, description `#description-textarea #textbox`, not-for-kids radio `tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]`, wizard `#next-button`/`#done-button`, visibility radios `name="PRIVATE|UNLISTED|PUBLIC"`. Codified in `studio_upload.tmpl.js`.

---

## Prompt tuning

Track changes to codex prompts: script generation (Korean tone, length, hook),
metadata (title/description/tags), and storyboard image prompts. Record the
before/after intent and the observed quality delta.

- 2026-06-03 — Storyboard character consistency: a fixed style suffix plus an explicit "same main character / palette / world" clause in every scene image prompt kept the same person, outfit, and kitchen across scenes 1-3 (verified on real gen.sh output). Carry the same character description into each Flow `scene_prompts[i]` so the motion clips stay consistent too.
- 2026-06-03 — Title for reach: codex's literal title is fine, but a curiosity-gap hook ("아침에 휴대폰부터 보지 마세요 (집중력 3분 리셋)") reads more clickable. Consider asking codex for 3 viral title variants and picking one.
- 2026-06-03 — Stage 6 now emits `bgm_mood` (short English keywords) + `key_sentences` (2-4 verbatim narration sentences) from `write_script.py`. `bgm_mood` drives the music search; `key_sentences` drive the selective burned captions. Old `script.json` without these fields still runs: mood derives from youtube tags+title (else "calm ambient"), key sentences fall back to a sparse first+every-3rd heuristic.

---

## Failure modes seen

Track concrete failures with their root cause and the fix or workaround.
Examples to watch for: Flow out of credits, codex token/quota exhaustion,
image entitlement refused (gen.sh exit 7), Studio feature not enabled (empty
feed), OAuth `invalid_grant`, Data API `quotaExceeded`, delogo box drift.

- 2026-06-03 — Silent-failure hardening ("each stage must pass"): the orchestrator trusted each stage's `{"ok": true}` + exit-0, but a stage can exit 0 with a degraded artifact — a truncated/streamless Flow MP4, a SILENT narration (TTS emitted a valid-but-empty/silent WAV while `add_narration` still emitted `"tts": true`), an empty ideas file, or a storyboard with no rendered frames. Added `scripts/stage_gates.py` (ffprobe/ffmpeg verification) and a gate call after every stage in `auto_youtube_pipeline.py`; a failed gate raises `GATE FAILED after '<stage>'` so nothing degraded reaches the next stage or upload. Narration silence is detected via `volumedetect` mean dBFS vs `DEFAULT_SILENCE_DB` (-50). Proven by `tests/test_stage_gates.py` (RED+GREEN) and `tests/test_pipeline_gates.py` (degraded output hard-stops before upload).
- 2026-06-03 — Fallbacks made opt-in (real generation by default): `bgm_library.resolve` always fell through to a synthesized CC0 pad, masking the absence of a real track. `resolve(..., allow_synth=True)` now returns `None` when `allow_synth=False` and no real source resolves; `add_narration.py` gained `--allow-synth-bgm` (default off) and hard-stops with an actionable message otherwise. `--no-bgm` remains the explicit narration-only opt-out. Two integration tests that assumed always-on synth were updated to opt in, and a hard-stop test was added.
- 2026-06-03 — Attach silently wrong: a custom `--npm-cache` made npx install a different `@playwright/cli` version whose daemon could not see the CDP-attached session, so every scrape returned a JSON parse error (`ok:false`, `note:null`). Fix: default `--npm-cache` to empty so the system cache (and its CLI/daemon) matches the attach. Applies to harvest, google_flow_cli, upload_youtube_studio.
- 2026-06-03 — CDP attach failed on Chrome 148: `--remote-debugging-port` is ignored on the default profile. Fix: enable chrome://inspect "Allow remote debugging for this browser instance", then `attach --cdp=chrome`. The new endpoint omits `/json/*` HTTP discovery but Playwright still connects.
- 2026-06-03 — Flow poll hung at `dur:0, videos>=1`: Flow `<video>` tiles load lazily (readyState 0, duration 0) until activated. Fix: `flow_status.js` now `load()`s each video and waits for `loadedmetadata` before reading duration, so finished clips are detected and auto-downloaded. The `media.getMediaUrlRedirect` URL also only resolves quickly after the clip is played/loaded.
- 2026-06-03 — Account split blocks the Data API path: the channel (@공유-e4p, sharepoint889) is a different Google account than the GCP project (jarvis-mymac, csk917work), and the project's auth platform was unconfigured. Workaround: upload via the Studio browser (`upload_youtube_studio.py`). Flow video access was also missing on the channel account — generate under a Flow-enabled account/project and upload the resulting MP4.
- 2026-06-03 — Stage 6 BGM + selective subtitles added (`subtitles.py`, `bgm_library.py`, `audio_mix.py`; conductor `add_narration.py`). BGM is always present: Jamendo (CC-BY/CC-BY-SA/CC0 only, `JAMENDO_CLIENT_ID` env) with a CC0 synth-pad fallback so no-network/no-key runs never fail. Low gain (~0.16) + sidechain ducking (`threshold=0.03:ratio=8:attack=20:release=300`) keeps narration clearly audible; `amix ...:normalize=0` stops auto-attenuation. Captions are drift-free because each sentence is synthesized separately, ffprobed, and the SAME WAVs are concatenated for the muxed audio. Burning the ASS forces a libx264 re-encode (matches existing delogo/assemble re-encodes). Attribution (when required) -> `CREDITS.txt` + `--extra-description` on the uploaders.

---

## TODO

Planned improvements and known gaps.

- [ ] Wire the full multi-scene Flow path into `auto_youtube_pipeline.py`
      (loop `scene_prompts` -> `generate_video` per scene -> `assemble_flow_video`),
      with `build_slideshow` and `upload_youtube_studio` as selectable backends.
- [ ] Auto-detect the Flow watermark box per resolution instead of fixed defaults.
- [x] Flow-free fallback renderer (`build_slideshow.py`) — done 2026-06-03.
- [x] Browser Studio uploader for the account-split case
      (`upload_youtube_studio.py`) — done 2026-06-03.
- [ ] Ask codex for multiple viral title variants and auto-pick the best.
- [ ] Cache scraped ideas to avoid re-mining the same topics.
- [ ] Capture and store per-stage timings to spot slow stages.
