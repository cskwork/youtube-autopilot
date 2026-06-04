# Plan — youtube-autopilot landing page refresh

## Plain-language brief (for everyone)

The project already has a good-looking dark landing page (`docs/index.html`). It
was built for the old name and only covers the YouTube pipeline. We will refresh
that same page so it: (1) uses the new name **youtube-autopilot** everywhere
(already done), (2) adds a clear section for the new **commercial mode** (one
command makes a 30-second vertical app ad), and (3) shows the project is now
**open source under MIT**. We keep the existing proven look and layout — this is
an enhancement, not a redesign — so the page stays fast, single-file, and ready
for GitHub Pages.

## Technical brief (for a junior dev)

- Target: `docs/index.html` — one self-contained file, inline CSS, no external
  requests. Keep current design tokens, nav, hero, pipeline, features, gate,
  fallbacks, quick-start sections.
- Add a **Commercial mode** section (after Product/fallbacks, before Quick start):
  headline + 2-3 sentence explainer + a `generate_commercial.py` command card +
  a small "pipeline" line (captures + Flow B-roll -> concat -> ducked music ->
  Korean TTS -> 1 MP4). Reuse existing `.cmd`/`.sec-head`/`.card` styles.
- Update hero/lede copy to mention BOTH outputs: private YouTube draft AND app
  commercial. Keep the existing stats; consider one stat tweak ("2 output modes").
- Footer: replace "Private project — all rights reserved" with
  "MIT licensed" linking to the LICENSE / GitHub.
- Verify: file parses as HTML, no "vimax" string, GitHub links point to
  `cskwork/youtube-autopilot`, contains a Commercial-mode section, mentions MIT,
  no external `http(s)://` asset includes (self-contained).

## Scope freeze

In scope: copy + one new section + footer license + commercial-mode content.
Out of scope: full redesign, new color system, build tooling, JS frameworks.
