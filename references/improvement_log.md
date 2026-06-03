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

---

## Failure modes seen

Track concrete failures with their root cause and the fix or workaround.
Examples to watch for: Flow out of credits, codex token/quota exhaustion,
image entitlement refused (gen.sh exit 7), Studio feature not enabled (empty
feed), OAuth `invalid_grant`, Data API `quotaExceeded`, delogo box drift.

- 2026-06-03 — Attach silently wrong: a custom `--npm-cache` made npx install a different `@playwright/cli` version whose daemon could not see the CDP-attached session, so every scrape returned a JSON parse error (`ok:false`, `note:null`). Fix: default `--npm-cache` to empty so the system cache (and its CLI/daemon) matches the attach. Applies to harvest, google_flow_cli, upload_youtube_studio.
- 2026-06-03 — CDP attach failed on Chrome 148: `--remote-debugging-port` is ignored on the default profile. Fix: enable chrome://inspect "Allow remote debugging for this browser instance", then `attach --cdp=chrome`. The new endpoint omits `/json/*` HTTP discovery but Playwright still connects.
- 2026-06-03 — Flow poll hung at `dur:0, videos>=1`: Flow `<video>` tiles load lazily (readyState 0, duration 0) until activated. Fix: `flow_status.js` now `load()`s each video and waits for `loadedmetadata` before reading duration, so finished clips are detected and auto-downloaded. The `media.getMediaUrlRedirect` URL also only resolves quickly after the clip is played/loaded.
- 2026-06-03 — Account split blocks the Data API path: the channel (@공유-e4p, sharepoint889) is a different Google account than the GCP project (jarvis-mymac, csk917work), and the project's auth platform was unconfigured. Workaround: upload via the Studio browser (`upload_youtube_studio.py`). Flow video access was also missing on the channel account — generate under a Flow-enabled account/project and upload the resulting MP4.

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
