# Verification — landing page refresh

Mode: GREENFIELD + UI/UX overlay. Builder (edits) and Verifier (this gate) separated;
gate is machine-checkable grep/HTML-parse, never edited to pass.

## Claims re-verified (all GREEN)

| # | Claim | run-to-prove | Verdict |
|---|-------|--------------|---------|
| 1 | No legacy brand left | `grep -ci vimax docs/index.html` → 0 | GREEN |
| 2 | GitHub links point to youtube-autopilot | 3 `cskwork/youtube-autopilot`, 0 `cskwork/vimax` | GREEN |
| 3 | Commercial mode section exists | `id="commercial"` ×1, `generate_commercial.py` ×2 | GREEN |
| 4 | MIT license surfaced | `MIT` ×2 (footer link + copyright) | GREEN |
| 5 | Self-contained / Pages-ready | no external `src/href` http asset includes | GREEN |
| 6 | Valid HTML structure | doctype present, 6 `<section>`/6 `</section>`, tag stack empties | GREEN |

## Coverage

Acceptance criteria: rename (1,2), commercial mode (3), MIT (4), single self-contained
file (5,6) — all covered.
Not covered: live rendering screenshot/visual diff (no browser run in this gate);
the page is static content over the existing proven design, so visual regression risk
is low and the layout reuses unchanged tokens/sections.
Regression tests: the six grep/parse checks above are re-runnable from a clean checkout.

verdict: GREEN
Decision: GO
