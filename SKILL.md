---
name: youtube-autopilot
description: Produce a video from a URL, a topic/YouTube inspiration idea, or faithful product UI captures using the bundled production pipelines. Use for finished video or private YouTube draft requests; upload and paid generation require authorization for those actions.
---

# YouTube Autopilot

Choose the workflow matching the user's input and requested output. Produce the finished video; upload only when requested. Private upload is still an external action. Public release remains a separate user decision.

## Route

State the chosen workflow briefly and read only its specification before running stages.

| Input and purpose | Workflow |
|---|---|
| URL/site/landing page turned into a video, with the page visible | [references/workflows/url-ad.md](references/workflows/url-ad.md) |
| Topic, Studio inspiration feed, or a rerun of an idea-to-draft stage | [references/workflows/idea-video.md](references/workflows/idea-video.md) |
| App/product commercial with supplied captures or no public URL | [references/workflows/product-ad.md](references/workflows/product-ad.md) |

Prefer url-ad when the URL's page is the subject; product-ad when supplied captures are the visual source. Ask only if the intended source/output remains materially ambiguous. Preserve real UI fidelity rather than regenerating product text as imagery.

## Execution boundaries

- Recover authorization from the current task before paid generation, authenticated account actions, or upload. Reuse approval for the same scope; do not ask at every repeated CLI invocation or recommend blanket permission rules.
- Default upload privacy is `private`. Do not change a draft to public as a verification step.
- Keep credentials in the supported secret files/arguments; never print their contents or hardcode them. Do not delete an existing token/profile to fix auth without authorization.
- Honor stage failures. A failed artifact must not reach upload. Resume only from a valid stage after a corrective change.
- Synthesized BGM requires explicit `--allow-synth-bgm`; without a usable licensed track, BGM-on runs stop. Do not silently substitute a synth pad.
- Inspect what `--dry-run` actually does before using it: a fixture run is not proof of live browser generation or upload. Do not label a path offline if it still calls narration, models, or a network source.

## Browser and prerequisites

Use the installed browser driver and current help/schema. Public url-ad ingest can launch a fresh browser; Studio/Flow/authenticated ingest require an authorized logged-in session. Reuse one CLI session and working directory across related stages.

For this package's Playwright CLI helpers, use a consistent package version and npm cache across attach and subsequent calls; switching caches can select a different daemon. `run-code` runs in Node context, while DOM inspection belongs in `page.evaluate`. Verify the selected tab/session before acting. Browser version, remote-debugging setup, and entitlement requirements must be checked in the current environment rather than inferred from historical Chrome observations.

Read [requirements.txt](requirements.txt) for Python dependencies. Relevant stages require `ffmpeg`/`ffprobe`; burned captions require libass, and BGM mixing uses `sidechaincompress`, `afade`, and `amix`. Check these capabilities before a run that needs them. Use configured model/Flow/Supertonic access and existing YouTube credentials only as authorized; setup is not implicitly authorized by a video request.

## Artifact gates

`scripts/auto_youtube_pipeline.py` orchestrates stages and writes `manifest.json`. `scripts/stage_gates.py` enforces machine-checkable minimums:

| Stage | Required evidence |
|---|---|
| Harvest | Parseable ideas with the selected index present |
| Storyboard | Valid storyboard and real scene image files |
| Script | Nonempty narration and Flow prompt |
| Video/delogo | Real video stream, sufficient duration and size |
| Narration | Video/audio streams, sane duration, nonsilent audio |
| URL ingest | Grounded URL, title, CTA and value propositions |
| URL ad script | Hook/duration limits, narrated key sentences, and captioned closing CTA |

Read workflow-specific contracts for thresholds and flags. These gates do not prove visual fidelity, factual accuracy, pronunciation, music rights, or a successful/private upload. Inspect those outcomes separately. Do not lower thresholds simply to pass a failed artifact.

For operational failure diagnosis, read the relevant stage in [references/runbook.md](references/runbook.md). Use [references/ad-creative.md](references/ad-creative.md) for url-ad creative direction. Record a durable selector/prompt correction in `references/improvement_log.md` only when actually changing this package, not merely using it on another project. Vendored `scripts/google_flow_cli.py` remains upstream code unless a separately scoped change is required.

## Verification and delivery

For package changes, run the relevant offline tests; the full suite is:

```bash
python3 -m pytest -q
```

Compile Python source for syntax checks rather than invoking every file with `--help`: not every module is a CLI. `tests/test_stage_gates.py` and `tests/test_pipeline_gates.py` cover degraded-artifact rejection and stopping before upload.

For a produced video, probe streams/duration and inspect the final picture, captions, critical narration, and licensed BGM credits. Compare the result with the chosen workflow's requested claims and UI. If upload was authorized, reopen the returned Studio draft, verify title/description and `private` status, then stop. Return the MP4 and, when created, the private draft link with observed verification and material limitations. Do not publish publicly to complete a check.
