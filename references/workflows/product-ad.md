# Workflow: product-ad

Advertise an EXISTING product (an app, site, or device with a real UI) whose
real screens must appear FAITHFULLY. Routed from `SKILL.md` Step 0 when the user
supplies real screen captures, or the product has no public URL to ingest, or
the user explicitly wants a hybrid real-UI + B-roll ad / a one-shot 30s app
commercial. Shares the building blocks and contracts in `SKILL.md`.

When the input is a public URL and the page itself should appear on screen,
prefer the `url-ad` workflow (`references/workflows/url-ad.md`), which captures
the page automatically; this workflow is for product-supplied/captured screens.

<product_ad_mode>
Advertising an EXISTING product (an app, site, or device with a real UI) adds
exactly one rule to the pipeline: the product's real screens must appear
FAITHFULLY. Generative video re-renders whatever it is seeded with, so feeding a
real UI screenshot through Flow garbles its text and layout. So in product-ad
mode the timeline is HYBRID, and this rule is domain-agnostic — the product,
its screens, and the script are inputs, never hardcoded:

- Flow renders only B-roll/atmosphere (people, hands, environment, mood). It is
  NEVER seeded with the product UI itself.
- Real product screens are captured from the live product (or supplied by the
  user) and shown VERBATIM as Ken-Burns motion clips via
  `build_kenburns_clip.py` (sharp pixels, subtle pan, blurred-cover background,
  fixed WxH/fps). They are never sent to a generative model.
- Both clip kinds are normalized to ONE geometry and concatenated with
  `assemble_flow_video.py`; delogo runs per Flow clip only (real screens carry
  no watermark). Narration/BGM/captions (`add_narration.py`) and upload then
  proceed unchanged.
- Capture real screens with the SAME attached browser used for Flow/Studio:
  navigate the live product, set the target viewport, screenshot; when a screen
  needs data to render, seed the product's own storage (e.g. localStorage)
  rather than mocking the UI. Provided assets are equally valid inputs.

Net effect: the audience sees the genuine product UI, while Flow supplies only
the cinematic surround.
</product_ad_mode>

<commercial_mode>
For a self-contained 30-second VERTICAL app commercial, `generate_commercial.py`
is a one-shot path over the same building blocks (no 7-stage orchestrator):
real product captures + Google Flow B-roll -> concat -> independent ducked
background music -> Supertonic Korean narration -> one MP4. It shares the
vendored `google_flow_cli.py`.

```bash
# Fresh Flow render from product captures (needs an attached Flow browser session)
python3 scripts/generate_commercial.py \
  --capture-dir examples/speakcoach/captures \
  --transcript-file examples/speakcoach/transcript_ko.txt \
  --run-flow \
  --flow-project-url "https://labs.google/fx/ko/tools/flow/project/YOUR_FLOW_PROJECT_ID" \
  --out-dir ./out

# Compose from an existing >=30s Flow hero clip (no Flow submit)
python3 scripts/generate_commercial.py \
  --flow-clip ./flow_30s.mp4 --transcript-file ./transcript_ko.txt --out-dir ./out
```

The bundled `SCENES`/`flow_prompt` are an editable SpeakCoach-style template;
the GENERIC path is `<product_ad_mode>` above. Fonts resolve cross-platform
(macOS/Windows/Linux); override with the `COMMERCIAL_FONT` env var. On success it
prints one JSON line: `{"ok": true, "final": <path>, ...}`. Worked inputs live in
`examples/speakcoach/` (the rendered demo MP4 is not committed — reproduce it).
</commercial_mode>
