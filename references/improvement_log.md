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

- (none yet)

---

## Prompt tuning

Track changes to codex prompts: script generation (Korean tone, length, hook),
metadata (title/description/tags), and storyboard image prompts. Record the
before/after intent and the observed quality delta.

- (none yet)

---

## Failure modes seen

Track concrete failures with their root cause and the fix or workaround.
Examples to watch for: Flow out of credits, codex token/quota exhaustion,
image entitlement refused (gen.sh exit 7), Studio feature not enabled (empty
feed), OAuth `invalid_grant`, Data API `quotaExceeded`, delogo box drift.

- (none yet)

---

## TODO

Planned improvements and known gaps.

- [ ] Auto-detect the Flow watermark box per resolution instead of fixed defaults.
- [ ] Cache scraped ideas to avoid re-mining the same topics.
- [ ] Add a dry-run mode that stops before upload for manual review.
- [ ] Capture and store per-stage timings to spot slow stages.
