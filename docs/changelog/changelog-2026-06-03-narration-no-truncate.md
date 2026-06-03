# Changelog 2026-06-03 — Narration no longer truncated by a short clip

## Why

User report from the live run: "영상이 말하다 다 안 끝났는데 끊기는 경우들이 발생하네"
— videos cut off while the narration was still talking.

Root cause: `add_narration.mux_final` muxed video + narration with `-shortest`.
`-shortest` ends the output at the SHORTER input. A Flow clip is a fixed ~8s,
but a multi-sentence Korean narration runs longer (the reported case: clip 8.0s
vs captions running to ~13.0s). So the last ~5s of the voiceover was cut off
mid-sentence. The narration gate still passed (audio present, not silent,
duration above the floor) because it never checked that the WHOLE narration fit.

## What changed

- `scripts/add_narration.py`
  - New `_video_filters(src, audio, burn_ass)`: computes
    `pad = narration_duration - clip_duration` and, when positive, prepends
    `tpad=stop_mode=clone:stop_duration=<pad>` so the video freeze-holds its last
    frame up to the narration length. The caption burn (`ass`) is appended AFTER
    `tpad`, so cues over the held tail still render onto the cloned frames.
  - `mux_final` now builds the `-vf` chain from `_video_filters`, re-encodes
    (libx264) whenever any filter is present, keeps `-c:v copy` only when there is
    no filter and the source is already h264, and still passes `-shortest` — which
    now lands the output exactly at the narration end (video >= audio after pad).
  - Net effect: output length == narration length; the full voiceover always
    plays. A clip shorter than the VO is freeze-padded, never truncated.
  - For continuous motion across the whole runtime (instead of a held tail), the
    multi-scene path remains: one Flow clip per scene + `assemble_flow_video.py`
    `setpts` stretch to the narration.

## Verification

- `python3 -m pytest -q` -> 91 passed (was 90; +1).
- New `tests/test_add_narration_integration.py::test_video_freeze_padded_to_full_narration_not_truncated`:
  stub TTS emits ~1.0s/sentence => ~3.0s narration over a 2.0s placeholder clip.
  - WITHOUT the fix (stashed): output 2.00s -> assertion `>= 2.9` FAILS (RED),
    reproducing the truncation.
  - WITH the fix: output ~3.0s -> PASSES (GREEN). Full suite green, no regressions
    (existing subtitle/BGM/legacy/hard-stop tests unaffected).

## Note

Video generation was stopped at the user's request; this is a skill fix only.
Video #1 from the earlier run was uploaded as a PRIVATE draft with the OLD
(truncated) mux and should be deleted/replaced before any future run re-uploads
with the fixed mux.
