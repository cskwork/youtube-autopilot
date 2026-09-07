# YouTube Autopilot — Runbook

Operational guide for running the pipeline by hand and debugging each stage.
Within authorized generation/upload scope, the pipeline stops at a private draft. Public release is a separate user decision.

Stages, in order:

1. **Inspiration** — scrape a channel idea from YouTube Studio (fallback: trending).
2. **Script** — codex writes a Korean script + metadata (title/description/tags).
3. **Storyboard** — codex (gpt-image-2 skill) renders reference frames.
4. **Video** — Google Flow renders an MP4 from the prompt + reference images.
5. **Narration** — Supertonic TTS synthesizes Korean voice; ffmpeg muxes it.
6. **Delogo** — ffmpeg `delogo` filter wipes the Flow watermark.
7. **Upload** — YouTube Data API v3 uploads the final MP4 as `private`.

Each script prints exactly one `{"ok": true, ...}` JSON line to stdout on
success; all logs go to stderr. Treat a non-zero exit, or the absence of that
final stdout line, as failure.

---

## Prerequisites (one-time)

- **Chrome with remote debugging**, logged into the target Google account, with
  access to BOTH YouTube Studio and Google Flow (labs.google). The Playwright
  agent CLI attaches over CDP endpoint `chrome`.
- **codex CLI** logged in via ChatGPT (`codex login status` => "Logged in using
  ChatGPT"). Needs the `image_generation` entitlement for storyboards.
- **YouTube OAuth client secret** (Desktop app) JSON downloaded from Google
  Cloud Console; used once to bootstrap a cached token.
- Python deps: `pip install -r requirements.txt`.
- `ffmpeg` and `ffprobe` on PATH (for mux, duration, and delogo).

---

## Stage 1 — Inspiration (attach)

Start Chrome with remote debugging so the Playwright CLI can attach over CDP:

```bash
# macOS example; close other Chrome windows first or use a separate profile.
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.config/youtube-autopilot-chrome-profile"
```

Then sign into the Google account (Studio + Flow) in that window.

Debug checklist:

- `npx @playwright/cli@latest attach --cdp=chrome -s=flow` must succeed. First
  run downloads the package — approve it. If it cannot find Chrome, confirm the
  remote-debugging port is open (`curl http://localhost:9222/json/version`).
- Studio uses Shadow DOM + virtualized lists; the scraper scrolls and pierces
  shadow roots. If `count` is 0, the inspiration/research feature may not be
  enabled for the channel — the pipeline falls back to youtube.com trending.
- To inspect live, run a quick eval:
  `npx @playwright/cli@latest -s=flow eval '"location.href"'`.

---

## Stage 2 — Script (codex auth)

Confirm codex is logged in before scripting:

```bash
codex login status   # expect: Logged in using ChatGPT
```

Debug checklist:

- "Not logged in" => run `codex login` and complete the browser flow.
- Raw stdout interleaves reasoning lines; scripts use `-o FILE` (final message
  only) or `--output-schema` for strict JSON. If JSON parse fails, re-read the
  `-o` output file directly — that file holds ONLY the final answer.
- Each call costs time + tokens (a trivial call reported ~33k tokens). Budget
  retries accordingly; do not loop blindly.

---

## Stage 3 — Storyboard (gpt-image-2)

Storyboard frames are produced via the gpt-image-2 skill's `gen.sh`, which
diffs `~/.codex/sessions` to extract the embedded PNG.

Debug checklist:

- Exit 7 = `imagegen` did not run (missing entitlement / quota / capability
  refused). Verify the ChatGPT plan includes image generation.
- `--enable image_generation` is REQUIRED and is set inside gen.sh; never add
  `--ephemeral` (it skips persisting the rollout, so the PNG has nowhere to
  live).
- extract_image.py picks the LARGEST image blob in the rollout. If a prompt
  makes codex emit a thumbnail plus the full image, the wrong one can win —
  keep storyboard prompts to one image per call.
- Output ext must be png/jpg/jpeg/webp and not under a system dir.

---

## Stage 4 — Video (Flow credits)

The Flow project URL is fixed in defaults. `google_flow_cli.py` attaches,
composes a text-to-video prompt with optional reference frames, polls, and
downloads ONLY the new post-submit MP4.

Debug checklist:

- "No new video appeared" within `--timeout` (default 420s): Flow may be out of
  credits, or the render queue is slow. Raise `--timeout` / `--poll-interval`,
  and confirm credits in the Flow UI of the attached browser.
- If direct fetch of the video `src` fails, the CLI falls back to the
  download-button JS template (`flow_download_button.tmpl.js`).
- Use `--fresh` to reload the Flow project before composing when the tab is in a
  stale state. Use `--no-attach` to reuse an already-attached session.
- Validate the MP4: the CLI checks the `ftyp` magic at bytes 4-8; a download
  that fails this is rejected.

---

## Stage 5 — Narration (Supertonic TTS + ffmpeg mux)

Korean narration default: Supertonic F1 (Mina), speed 0.95, steps 16, lang ko.
The same resolution + synthesis + mux patterns also drive commercial mode in
`scripts/generate_commercial.py`.

Debug checklist:

- If the Supertonic command cannot be resolved, confirm the TTS binary/venv is
  installed and on PATH; the resolver tries known command names in order.
- ffprobe must return a positive duration for both the video and the synthesized
  audio; a zero/None duration usually means a failed synth or a corrupt file.
- When muxing, the audio is fit to the video length; mismatch warnings go to
  stderr.

---

## Stage 6 — Delogo box tuning

Flow stamps a watermark; ffmpeg `delogo` blurs a rectangle over it.
The box is `x:y:w:h` in pixels. Defaults target the bottom-right corner of a
16:9 1920x1080 frame, but the exact position drifts with resolution and Flow UI
changes.

Tuning procedure:

1. Grab one frame: `ffmpeg -i in.mp4 -frames:v 1 -ss 1 frame.png`.
2. Open `frame.png`, read the watermark's bounding box in pixels.
3. Set `delogo=x=X:y=Y:w=W:h=H`. Add a few px of margin on every side so the
   filter has clean surrounding pixels to interpolate from.
4. Re-render a 2-second clip and eyeball it. If you see a ghost edge, grow the
   box slightly; if you smear real content, shrink it.
5. For non-1080p output, scale the box proportionally to the actual width/height
   (read them with `ffprobe -v error -select_streams v:0 -show_entries
   stream=width,height`).

---

## Stage 7 — Upload + OAuth token bootstrap

Upload uses YouTube Data API v3 with `privacyStatus=private`. Token cache
default: `~/.config/youtube-autopilot/token.json`.

First-time token bootstrap (interactive, run once):

1. In Google Cloud Console, enable **YouTube Data API v3** and create an OAuth
   **Desktop app** client. Download the client secret JSON.
2. Run the upload script's auth/bootstrap path, passing the client secret via
   CLI arg (never hardcoded). It opens a browser, you consent, and the refresh
   token is written to the token cache.
3. Subsequent runs reuse and silently refresh the cached token; no browser.

Debug checklist:

- `invalid_grant` / expired refresh token: inspect the auth failure and use the supported reauthorization flow. Replace an existing token cache only with authorization.
- 403 `quotaExceeded`: the Data API daily quota is spent (a single upload costs
  ~1600 units). Wait for the quota reset or request more.
- 401 / scope errors: the cached token lacks the upload scope. Do not delete an existing token cache without authorization; inspect scopes and use the supported reauthorization flow. Replace the cache only when authorized
  and re-consent.
- Authorized uploads land as **private**. Verification leaves the draft private; public release is a separate user decision.
