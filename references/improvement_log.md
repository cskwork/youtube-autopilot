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

- 2026-06-03 — Studio upload title kept a 'narrated' suffix + made duplicate drafts (live, SpeakCoach ad): (1) the Details title box AUTO-FILLS from the uploaded filename (`narrated.mp4` -> "narrated"); `studio_upload.tmpl.js` `setBox` did a single select-all+Backspace that didn't always clear it, so the typed title landed as "<title>narrated". Fix: `setBox` now verifies the box is empty and triple-clicks to hard-select + Backspace before inserting (mirrors the standalone `fix_title.js` used to repair the live drafts). (2) Each `goto …/videos/upload?d=ud` + `setInputFiles` CREATES a draft, so a retry after a transient failure left DUPLICATE private drafts — don't blindly re-run the whole uploader; either continue the already-open modal (set title/desc/next/done without re-selecting the file) or delete the extras. The vertical 1080x1920 / 39s ad also lands under the channel's **Shorts** tab, not the long-form 동영상 list — verify there.
- 2026-06-03 — Captions restyled Korean-variety/TV-show (user-requested): static white box read flat. `subtitles.build_ass` now cycles a colour+position palette (`_CAPTION_PRESETS`: yellow/cyan/pink/green, mostly `\an2` bottom with one `\an8` top for rhythm) and POPS key words inline (accent `\c` + larger `\fs` + `\b1` + a quick `\t(0,140,\fscx100\fscy100)` scale settle), with a per-line `\fad`. Emphasis terms are derived domain-agnostically from `script.json` youtube tags (`add_narration.emphasis_terms`, split into alnum tokens); with none, each caption pops its longest token. Capped at 2 emphasised tokens/caption so a line never becomes a wall of colour. Tests: `test_variety_captions_styling`, `test_variety_emphasis_falls_back_to_longest_token`.
- 2026-06-03 — Burned captions overflowed on Shorts (user-reported): `subtitles._ASS_HEADER` hardcoded `PlayResX/Y 1280x720` + `WrapStyle 2` (no auto-wrap). On a 1080x1920 (9:16) frame libass scales the script Y axis ~2.67x, so the font ballooned and every un-wrapped Korean line ran off both edges. Fix: `_ass_header(width, height)` now sets `PlayRes` to the REAL frame (1:1 scaling), uses `WrapStyle 0` (smart wrap within side margins), and BRANCHES by format — Shorts/portrait gets a larger phone-legible font (≈width*0.05) and a tall bottom margin (≈height*0.13) to clear the Shorts UI, while standard/landscape reproduces the historical 16:9 look (1280x720 -> font 44, MarginV 60). `build_ass(segments, key_idx, width, height)` and `add_narration` (probes the input video's WxH) thread the frame size through. Proven by `tests/test_subtitles.py::test_ass_playres_matches_frame_and_wraps` and `::test_shorts_vs_standard_caption_sizing_differs`.
- 2026-06-03 — Product-ad mode added (advertising an existing app/site/device): feeding real UI screenshots through Flow garbles their text/layout, so real screens must NOT be generated. New `build_kenburns_clip.py` renders each real screenshot as a faithful fixed-geometry Ken-Burns clip (blurred-cover bg, subtle diagonal pan, sharp UI); Flow is restricted to lifestyle/atmosphere B-roll; both clip kinds normalize to one WxH and concat via `assemble_flow_video.py` with delogo applied per Flow clip only (real screens have no watermark). Real screens captured by driving the SAME attached browser (set viewport, navigate routes, screenshot; seed the product's own localStorage for data-dependent screens). Documented in SKILL.md `<product_ad_mode>`. First used for the SpeakCoach EDU app ad (real screens: home/practice/missions/rewards/settings at 1080x1920).
- 2026-06-03 — Storyboard frames render 16:9 on a 9:16 run: `auto_youtube_pipeline.py` forwards `--aspect-ratio` to `generate_video` but NOT to `make_storyboard` (which keeps its own `--aspect` default 16:9), and gpt-image-2 treats the "Aspect ratio X" text as only a weak hint — so 5/6 frames came out landscape on a Shorts run. Workaround: regenerate frames with a strong "Portrait vertical 9:16, tall full-bleed composition" prefix plus one reference frame to anchor orientation/character. Real fix: thread `aspect_ratio` into the make_storyboard stage and map it to an explicit gen.sh size. (Mostly moot in product-ad mode, where real screenshots replace generated frames.)
- 2026-06-03 — Narration cut off mid-sentence (user-reported on the live 8s-Shorts run): `add_narration.mux_final` muxed with `-shortest`, so the output took the SHORTER of the ~8s Flow clip and the ~13s voiceover — the clip won and the narration was truncated mid-word (clip 8.0s vs captions running to ~13.0s). Root cause: an 8s Flow clip can't hold a multi-sentence Korean narration. Fix: `_video_filters` freeze-pads the video with `tpad=stop_mode=clone:stop_duration=<narration-clip>` up to the narration length (applied BEFORE the ASS burn so tail cues still render), and `-shortest` then lands the output exactly at the narration end — the full VO always plays, output length == narration. For motion across the whole runtime instead of a held tail, use the multi-scene path (`assemble_flow_video.py` `setpts` stretch). Proven by `tests/test_add_narration_integration.py::test_video_freeze_padded_to_full_narration_not_truncated` (RED 2.0s without the fix, GREEN ~3.0s with it).
- 2026-06-03 — BGM hard-stop on a legacy `script.json` (no `bgm_mood`): when `script.json` predates the Stage 6 fields, `resolve_mood` falls back to `youtube.tags + title`, producing a long KOREAN mood string ("아침루틴 집중력 생산성 집중 안 되는 아침, 3분이면 다시 시작됩니다"). Jamendo is English-indexed, returns zero hits for it, and (correctly, real-by-default) `add_narration` hard-stops instead of degrading to synth. Fix when reusing an old script: pass `--bgm-mood "<short English keywords>"` (e.g. "calm morning ambient lofi piano") — Jamendo then resolved a CC-BY track ("Leave and Never Look Back" by madelyn munsell) and the run completed. Better long-term: have `write_script.py` always emit a short English `bgm_mood`, and/or transliterate the Korean fallback to English before the Jamendo query. Observed driving the real content #1 upload.
- 2026-06-03 — Agent harness blocks the live attach without approval: the browser stages shell out to `npx @playwright/cli@latest` (an external, non-manifest package) and the attach/upload spends credits and is hard to reverse, so Claude Code's auto-permission classifier denied the attach ("Runs an agent-chosen external package ... begins the live-upload Chrome attach the user explicitly deferred"). This is the intended human gate, not a bug. A one-time attach approval is insufficient because harvest, Flow, and Studio upload each re-invoke the CLI; the operator must grant a standing allow rule for `npx @playwright/cli@latest *` (or run the attach via the shell `!` prefix and approve each stage). Documented in SKILL.md `<browser_attach>` point 6 + `<important_constraints>`.
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
- [ ] Wire product-ad mode into the orchestrator: a `--product-shots <dir>` (or
      manifest) input that routes real screens through `build_kenburns_clip.py`
      and restricts Flow to B-roll scenes, then normalizes + concats both.
- [ ] Thread `--aspect-ratio` into `make_storyboard` and map it to an explicit
      gen.sh image size (storyboard frames currently default to 16:9).
- [x] Flow-free fallback renderer (`build_slideshow.py`) — done 2026-06-03.
- [x] Browser Studio uploader for the account-split case
      (`upload_youtube_studio.py`) — done 2026-06-03.
- [ ] Ask codex for multiple viral title variants and auto-pick the best.
- [ ] Cache scraped ideas to avoid re-mining the same topics.
- [ ] Capture and store per-stage timings to spot slow stages.
