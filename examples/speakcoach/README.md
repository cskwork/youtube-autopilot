# SpeakCoach commercial example

A worked input set for **commercial mode** (`scripts/generate_commercial.py`): a
SpeakCoach EDU app ad built from real product screen captures + Google Flow
B-roll + Supertonic Korean narration.

## What's here

- `captures/speakcoach_*.png` — the five real app screens the commercial is
  built from (`home`, `practice`, `missions`, `rewards`, `settings`).
- `transcript_ko.txt` — the Korean narration script.
- `output/manifest.json` — the manifest from a real run.

> The rendered demo MP4s are **not committed** (the repo ignores `*.mp4` to stay
> light). Reproduce them from the inputs above.

## Reproduce

Fresh Google Flow render from the captures (needs an attached Flow browser
session — see the main README's "Browser attach"):

```bash
python3 scripts/generate_commercial.py \
  --capture-dir examples/speakcoach/captures \
  --transcript-file examples/speakcoach/transcript_ko.txt \
  --run-flow \
  --flow-project-url "https://labs.google/fx/ko/tools/flow/project/YOUR_FLOW_PROJECT_ID" \
  --out-dir ./out
```

Or, if you already have a >=30s Flow hero clip, skip Flow and just compose:

```bash
python3 scripts/generate_commercial.py \
  --flow-clip ./flow_30s.mp4 \
  --transcript-file examples/speakcoach/transcript_ko.txt \
  --out-dir ./out
```

The bundled `SCENES` / `flow_prompt` in `generate_commercial.py` are a
SpeakCoach-style template — edit them for a different app, or use the generic
`<product_ad_mode>` of the main pipeline.
