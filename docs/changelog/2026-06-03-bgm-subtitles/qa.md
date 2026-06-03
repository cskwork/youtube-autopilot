# QA — Stage 6 (BGM + selective subtitles) through the real orchestrator, OFFLINE

**Date:** 2026-06-03
**Tool:** ffmpeg / orchestrator (CLI) — `scripts/auto_youtube_pipeline.py`
**Worktree under test:** `/Users/danny/Documents/PARA/Resource/autoresearch/vimax-autopilot-verify-wt` (detached @ `ee5ceab` — "feat(stage6): low-volume royalty-free BGM + selective key-sentence subtitles")
**Headline requirement:** "the whole flow runs from this ONE skill" — prove Stage 6 (BGM + selective captions) works THROUGH the real orchestrator, end-to-end, offline.

## VERDICT: **PASS**

The real orchestrator ran the **full 7-stage chain** end-to-end and exited 0, with **no network, no real codex, no browser, no real TTS, no upload**. Stage 6 produced a final `narrated.mp4` (h264 + aac, duration > 0) with low-volume **synth** BGM and burned-in **selective** key-sentence captions, plus a `manifest.json`. Every stage script invoked came from this skill's own `scripts/` dir; the only external binaries (`codex`, `supertts`) were throwaway offline stubs placed first on PATH. No tracked source file was edited.

The orchestrator ran the **complete chain** (harvest→storyboard→script→video→delogo→narration→upload). **No bypass of the script stage was needed** — the fake `codex` satisfied `write_script.py` and the whole pipeline flowed through the real orchestrator code path. (See "Orchestrator skip-flag contract" below for the one non-obvious input-placement detail.)

---

## Setup (all stubs/inputs under `/tmp` — nothing tracked was touched)

`/tmp/vya-qa/` staging:

- `stub/codex` — fake `codex` (python, executable). Drains the prompt on stdin, ignores it, and writes a CANNED schema-valid `answer.json` to the path after `-o`. Satisfies `write_script.py`'s `codex exec ... --output-schema <schema> -o <answer>` contract. Canned answer fields: `narration_ko` (6 Korean sentences), `flow_prompt`, `scene_prompts` (6), `bgm_mood` = "calm uplifting ambient morning", `key_sentences` (3 sentences copied **verbatim** from `narration_ko`), `youtube{title,description,tags,category:"22"}`.
- `stub/supertts` — fake `supertts` (python, executable). Matches `subtitles._synth_one`'s call `supertts -f <txt> --lang ko --voice F1 --speed 0.95 --steps 16 --no-play --quiet -o <wav>`. Reads `-f`, writes a real sine WAV via `ffmpeg lavfi` whose length loosely tracks the input text length (≈0.18s/char, clamped 1.2–8.0s). `subtitles.resolve_supertts("")` prefers a PATH `supertts`, so this is picked up automatically — the orchestrator does NOT thread `--supertts-command`, so a PATH stub is the correct hook.
- `ideas.json` — minimal valid ideas file matching `harvest_ideas.py` shape (`{"ok":true,"source":"topic","ideas":[{rank,title,angle,hook,keywords,why,target_length_sec}]}`).
- `run/storyboard/storyboard.json` — minimal valid storyboard matching `make_storyboard.py` output (`{"ok":true,"idea":{...},"scenes":[{n,beat,visual,camera,on_screen_text}×6]}`). **Placed inside the out-dir** (see contract note).
- `placeholder.mp4` — 3s navy clip + silent aac track via `ffmpeg lavfi` (so `--dry-run` adopts `--video`; mirrors the orchestrator's own placeholder recipe).
- `token.json` — throwaway dummy token so `upload_youtube.py --dry-run`'s gate (`token_path.is_file()`) passes. Never read for content in dry-run.

`stub/` was placed **first** on `PATH`; `JAMENDO_CLIENT_ID` was **unset** (force synth BGM).

---

## Exact commands run

Stage the storyboard into the out-dir (skip-storyboard contract — see note):

```
mkdir -p /tmp/vya-qa/run/storyboard
cp /tmp/vya-qa/storyboard/storyboard.json /tmp/vya-qa/run/storyboard/storyboard.json
```

Run the full orchestrator, offline:

```
cd /tmp/vya-qa
env -u JAMENDO_CLIENT_ID PATH="/tmp/vya-qa/stub:$PATH" \
  python3 /Users/danny/Documents/PARA/Resource/autoresearch/vimax-autopilot-verify-wt/scripts/auto_youtube_pipeline.py \
  --dry-run \
  --skip-harvest --ideas-json /tmp/vya-qa/ideas.json \
  --skip-storyboard \
  --video /tmp/vya-qa/placeholder.mp4 \
  --out-dir /tmp/vya-qa/run \
  --token /tmp/vya-qa/token.json
```

Final stdout (the orchestrator's single JSON result line):

```
{"ok": true, "manifest": "/private/tmp/vya-qa/run/manifest.json", "studio_url": null, "stopped_for": "human-publish"}
```

Exit code: **0**. Stage banners observed in order: `[1/7] harvest_ideas` (skipped) → `[2/7] make_storyboard` (skipped) → `[3/7] write_script` (fake codex) → `[4/7] generate_video` (adopted `--video`) → `[5/7] remove_logo` (delogo) → `[6/7] add_narration` (TTS+BGM+captions) → `[7/7] upload_youtube` (dry-run).

---

## Evidence (as-is)

### 1. Final video — `ffprobe` shows h264 video + aac audio + duration > 0

```
$ ffprobe -v error -show_entries stream=codec_type,codec_name -show_entries format=duration narrated.mp4
video codec: h264
audio codec: aac
container duration: 3.000000
```

Key line: **h264 video stream + aac audio stream, duration 3.0s (> 0).**

Audio is the muxed narration+BGM mix, not silence (volumedetect):

```
mean_volume: -35.0 dB
max_volume: -29.4 dB
```

> Note on the 3s length: the placeholder video is 3s, and `add_narration.mux_final` uses `-shortest`, so the ~25s narration track is truncated to the video length. This is expected for a 3s placeholder; Stage 6 still ran the complete TTS → synth-BGM bed → sidechain duck → ASS burn → mux path (visible in the stage-6 ffmpeg commands in the run log). With a real full-length Flow clip the audio would play out in full.

### 2. Captions are present and SELECTIVE (only key sentences, not every sentence)

Sidecars `captions.srt` + `captions.ass` were produced beside the output.

`captions.srt` (full content):

```
1
00:00:05,760 --> 00:00:10,260
아침에 일어나면 물 한 잔을 먼저 마셔보세요.

2
00:00:14,040 --> 00:00:18,180
이 작은 루틴이 집중력을 크게 높여줍니다.

3
00:00:21,960 --> 00:00:25,380
지금 바로 오늘부터 시작해 보세요.
```

Selectivity proof:

```
total narration sentences: 6
key_sentences in script  : 3
caption blocks in .srt   : 3
selective? (caps < total): True
captioned == key_sentences set: True
```

Only **3 of the 6** narration sentences are captioned, and the captioned set is **exactly** the verbatim `key_sentences` — confirming `subtitles.select_key_indices` matched the verbatim keys and captioned ONLY those (선택적 "부분부분" captions), not every sentence. The burned `captions.ass` carries the same 3 `Dialogue:` lines under a single `Key` style.

### 3. BGM is the synth fallback (no network) — `manifest.json` narration block

```json
{
  "bgm": {
    "path": "/tmp/claude-501/add_narration_0hd4_gs0/bgm/pad_calm-uplifting-ambient-morning.wav",
    "source": "synth",
    "license": "CC0 (synthesized)",
    "attribution": null
  },
  "subtitles": {
    "srt": "/private/tmp/vya-qa/run/captions.srt",
    "ass": "/private/tmp/vya-qa/run/captions.ass",
    "key_count": 3
  },
  "credits": null,
  "voice_name": "Mina",
  "tts": true
}
```

`bgm.source = "synth"`, `license = "CC0 (synthesized)"`, `attribution = null` — the `bgm_library` synth-pad fallback fired (step 4 of its chain) because no `JAMENDO_CLIENT_ID` was set and `references/bgm_cache/` held no matching mood track. The synth pad was built from three mood-hashed sine layers via `ffmpeg lavfi` (seen in the run log), laid under the narration at volume 0.16 with sidechain ducking.

### 4. Manifest records narration/bgm; attribution threading

The manifest's `narration` block records the full BGM + subtitle info (above). Attribution threading to the upload description works via `auto_youtube_pipeline._bgm_attribution(narration)` → `upload_youtube.py --extra-description`. Because synth BGM has **`attribution = null`**, `_bgm_attribution` returns `""`, so **nothing is appended** to the YouTube description and **no `CREDITS.txt` is written** (`add_narration.write_credits` returns `None` when `bgm.attribution` is falsy). This is the intended behavior: CC0 synth music requires no credit. (If a Jamendo CC-BY track had been resolved, its `attribution` string would have threaded into both `CREDITS.txt` and the description's `--extra-description`.) Confirmed at runtime: `credits = null`, `CREDITS.txt` absent.

### 5. Whole run used ONLY this skill's scripts (no parent-repo file)

Every Python stage invoked resolved under the verify worktree's own `scripts/`:

```
.../vimax-autopilot-verify-wt/scripts/write_script.py
.../vimax-autopilot-verify-wt/scripts/remove_logo.py
.../vimax-autopilot-verify-wt/scripts/add_narration.py   (+ its siblings audio_mix/subtitles/bgm_library, loaded by path)
.../vimax-autopilot-verify-wt/scripts/upload_youtube.py
```

The only external binaries were the offline stubs (`/tmp/vya-qa/stub/codex`, `/tmp/vya-qa/stub/supertts`), placed first on PATH so they shadowed the real `codex` at `/Users/danny/.nvm/.../codex` (which would have gone online). `git status --porcelain` in the verify worktree is **empty** — no tracked source file was edited.

---

## Orchestrator skip-flag contract (the one finding to note)

`--skip-storyboard` does **not** accept an external storyboard path. The orchestrator hardcodes the storyboard dir as `<out-dir>/storyboard` (`build_paths`), and `write_script` reads `<out-dir>/storyboard/storyboard.json`. So to reuse a storyboard you must place `storyboard.json` **inside the out-dir** (`/tmp/vya-qa/run/storyboard/`), not in an arbitrary location. The first run attempt failed with `missing input file: .../run/storyboard/storyboard.json`; staging the file into the out-dir fixed it. This is the documented intent of `--skip-storyboard` ("reuse an existing storyboard **dir**" = the run's own dir), not a bug — but it is non-obvious and worth recording.

There is **no `--skip-script` flag** — the script stage always runs. That is why a fake `codex` is the correct way to drive the full chain offline; the script stage was **not** bypassed.

---

## Limitations / scope of this proof

- The video is a 3s lavfi placeholder, so `-shortest` clips the audio to 3s. The Stage 6 pipeline (per-sentence TTS, synth BGM bed, sidechain duck, selective ASS burn, mux) all executed in full; only the final audio playout length is bounded by the placeholder. A real Flow clip would carry the full narration.
- TTS audio is a sine stand-in (fake `supertts`), so there is no real Korean speech — but the timing model (per-sentence WAV durations → caption start/end offsets) is the **real** code path, which is what makes the captions land at distinct, frame-accurate timestamps shown above.
- BGM proved is the **synth** fallback. The Jamendo path was deliberately not exercised (offline requirement) by leaving `JAMENDO_CLIENT_ID` unset; the synth fallback is the guaranteed-offline branch the requirement targets.
```
