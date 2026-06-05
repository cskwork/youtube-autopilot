#!/usr/bin/env python3
"""End-to-end orchestrator for youtube-autopilot.

Chains the seven stage scripts as subprocesses in order:
  harvest_ideas -> make_storyboard -> write_script -> generate_video ->
  remove_logo -> add_narration -> upload_youtube

Each stage writes its artifacts into --out-dir; the orchestrator threads the
prior stage's output path into the next stage. A manifest.json records every
choice and artifact. The pipeline STOPS at the private YouTube draft and never
publishes: the only remaining human step is flipping private->public in Studio.

Stage scripts already follow the contract "exactly one JSON line on stdout,
logs on stderr"; this orchestrator does the same. On success it prints exactly
one JSON object:
  {"ok": true, "manifest": <path>, "studio_url": <url|null>,
   "stopped_for": "human-publish"}
On any stage failure it raises SystemExit with a clear message.

--dry-run runs harvest/storyboard/script/codex steps when possible but SKIPS
the real Flow submit (uses a provided --video or a generated 2s color clip) and
calls upload_youtube.py with --dry-run so nothing is uploaded.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_sibling(name: str):
    """Import a sibling scripts/ module by path (cwd-independent)."""
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


stage_gates = _load_sibling("stage_gates")

# Relative to the current working directory; override with --out-dir.
DEFAULT_OUT_DIR = ".working_dir/youtube-autopilot/run"
DEFAULT_FLOW_URL = (
    "https://labs.google/fx/ko/tools/flow/project/YOUR_FLOW_PROJECT_ID"
)
DEFAULT_FEED = (
    "https://studio.youtube.com/channel/YOUR_CHANNEL_ID"
    "/content/inspiration/feed"
)


# --- logging -----------------------------------------------------------------

def log(message: str) -> None:
    """Write a progress line to stderr; stdout is reserved for the JSON result."""
    print(message, file=sys.stderr, flush=True)


def stage_header(index: int, total: int, name: str) -> None:
    """Print a clear per-stage progress banner to stderr."""
    log("")
    log(f"=== [{index}/{total}] {name} " + "=" * max(0, 48 - len(name)))


def gate(stage: str, check) -> dict:
    """Run a stage_gates verification, hard-stopping the pipeline on failure.

    ``check`` is a zero-arg callable that runs the relevant gate and returns its
    info dict. A failed gate (degraded/missing/silent artifact) becomes a clear
    SystemExit so the chain NEVER carries a broken artifact to the next stage or
    to upload — this is what enforces "each stage must pass".
    """
    try:
        info = check()
    except stage_gates.GateError as exc:
        raise SystemExit(f"GATE FAILED after '{stage}': {exc}") from exc
    log(f"[gate] {stage} OK: {info}")
    return info


# --- subprocess stage runner -------------------------------------------------

def run_stage(name: str, cmd: list[str]) -> dict:
    """Run a stage script, stream its stderr live, parse its final stdout JSON.

    Stage scripts print exactly one JSON object on stdout and logs on stderr.
    We capture stdout to parse the result and let stderr inherit so the user
    sees live progress.
    """
    log(f"+ {name}: {subprocess.list2cmdline(cmd)}")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=None, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"stage '{name}' failed (exit {proc.returncode}); see logs above")
    return parse_result(name, (proc.stdout or "").strip())


def parse_result(name: str, stdout: str) -> dict:
    """Pick the last JSON object line from a stage's stdout and validate ok."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            if not result.get("ok"):
                raise SystemExit(f"stage '{name}' reported failure: {result}")
            return result
    raise SystemExit(f"stage '{name}' produced no JSON result line; stdout={stdout!r}")


def py(script: str) -> list[str]:
    """Return the base argv to run a sibling stage script with this interpreter."""
    return [sys.executable, str(HERE / script)]


def browser_args(args: argparse.Namespace) -> list[str]:
    """Shared session/attach flags so every browser stage uses one session."""
    extra = ["--session", args.session]
    if args.no_attach:
        extra.append("--no-attach")
    return extra


# --- dry-run placeholder video ----------------------------------------------

def make_placeholder_video(out: Path, seconds: int = 2) -> Path:
    """Generate a short solid-color clip with a silent track for dry runs.

    Used when --dry-run is set and the caller did not supply --video, so the
    later delogo/narration/upload stages have a real MP4 to operate on without
    spending Flow credits.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=navy:s=1280x720:d={seconds}:r=24",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", str(out),
    ]
    log(f"+ placeholder video: {subprocess.list2cmdline(cmd)}")
    subprocess.run(cmd, check=True)
    if not out.exists() or out.stat().st_size == 0:
        raise SystemExit(f"failed to create placeholder video at {out}")
    return out


# --- idea selection ----------------------------------------------------------

def select_idea(ideas_json: Path, index: int) -> dict:
    """Return the chosen idea dict from a harvest ideas file by 0-based index."""
    data = json.loads(ideas_json.read_text(encoding="utf-8"))
    ideas = data.get("ideas", data) if isinstance(data, dict) else data
    if not isinstance(ideas, list) or not ideas:
        raise SystemExit(f"no ideas array in {ideas_json}")
    if index < 0 or index >= len(ideas):
        raise SystemExit(f"--idea-index {index} out of range (have {len(ideas)})")
    return ideas[index] if isinstance(ideas[index], dict) else {"title": str(ideas[index])}


def write_idea_file(idea: dict, path: Path) -> Path:
    """Persist the single chosen idea so downstream stages can reference it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(idea, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --- stage 1: harvest --------------------------------------------------------

def stage_harvest(args: argparse.Namespace, paths: dict[str, Path]) -> Path:
    """Run harvest_ideas (or reuse --ideas-json) and return the ideas file path."""
    if args.skip_harvest:
        if not args.ideas_json:
            raise SystemExit("--skip-harvest requires --ideas-json")
        ideas = Path(args.ideas_json).expanduser().resolve()
        if not ideas.is_file():
            raise SystemExit(f"--ideas-json not found: {ideas}")
        log(f"[harvest] skipped; using {ideas}")
        return ideas
    cmd = py("harvest_ideas.py") + [
        "--out", str(paths["ideas"]),
        "--limit", str(max(args.idea_index + 1, 5)),
    ]
    if args.topic.strip():
        cmd += ["--topic", args.topic.strip()]
    else:
        cmd += ["--channel-url", args.channel_url, *browser_args(args)]
    run_stage("harvest_ideas", cmd)
    return paths["ideas"]


# --- stage 2: storyboard -----------------------------------------------------

def stage_storyboard(args: argparse.Namespace, ideas: Path, paths: dict[str, Path]) -> Path:
    """Run make_storyboard for the chosen idea; return the storyboard dir."""
    if args.skip_storyboard:
        log(f"[storyboard] skipped; using {paths['storyboard_dir']}")
        return paths["storyboard_dir"]
    cmd = py("make_storyboard.py") + [
        "--idea-json", str(ideas),
        "--idea-index", str(args.idea_index),
        "--scenes", str(args.scenes),
        "--aspect", args.aspect_ratio,
        "--out-dir", str(paths["storyboard_dir"]),
    ]
    run_stage("make_storyboard", cmd)
    return paths["storyboard_dir"]


# --- stage 3: script ---------------------------------------------------------

def stage_script(args: argparse.Namespace, idea_file: Path, paths: dict[str, Path]) -> Path:
    """Run write_script using the chosen idea + storyboard; return script path."""
    cmd = py("write_script.py") + [
        "--idea-json", str(idea_file),
        "--storyboard-json", str(paths["storyboard_dir"] / "storyboard.json"),
        "--out", str(paths["script"]),
        "--duration", str(args.duration),
        "--aspect-ratio", args.aspect_ratio,
    ]
    page_facts = paths.get("page_facts")
    if page_facts and Path(page_facts).exists():
        cmd += ["--page-facts-json", str(page_facts)]
    run_stage("write_script", cmd)
    return paths["script"]


# --- stage 4: video ----------------------------------------------------------

def stage_video(args: argparse.Namespace, script: Path, paths: dict[str, Path]) -> Path:
    """Produce the raw video: real Flow render, supplied file, or dry placeholder."""
    raw = paths["raw_video"]
    if args.skip_video:
        if not args.video:
            raise SystemExit("--skip-video requires --video")
        return _adopt_supplied_video(Path(args.video).expanduser().resolve(), raw)
    if args.dry_run:
        if args.video:
            return _adopt_supplied_video(Path(args.video).expanduser().resolve(), raw)
        log("[video] dry-run: generating a 2s placeholder clip (no Flow submit)")
        return make_placeholder_video(raw)
    cmd = py("generate_video.py") + [
        "--script-json", str(script),
        "--storyboard-dir", str(paths["storyboard_dir"]),
        "--out", str(raw),
        "--flow-project-url", args.flow_project_url,
        "--duration", str(args.duration),
        "--aspect-ratio", args.aspect_ratio,
        *browser_args(args),
    ]
    run_stage("generate_video", cmd)
    return raw


def _adopt_supplied_video(src: Path, dest: Path) -> Path:
    """Copy a user-supplied MP4 into the run dir as the raw video stage output."""
    if not src.is_file():
        raise SystemExit(f"--video not found: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    log(f"[video] using supplied video {src} -> {dest}")
    return dest


# --- stage 5: delogo ---------------------------------------------------------

def stage_delogo(raw: Path, paths: dict[str, Path]) -> dict:
    """Run remove_logo to wipe the Flow watermark; return its result dict."""
    cmd = py("remove_logo.py") + [
        "--in", str(raw),
        "--out", str(paths["delogo_video"]),
    ]
    return run_stage("remove_logo", cmd)


# --- stage 6: narration ------------------------------------------------------

def stage_narration(args: argparse.Namespace, delogo: Path, script: Path, paths: dict[str, Path]) -> dict:
    """Run add_narration: Korean TTS + low BGM + selective captions (default on)."""
    cmd = py("add_narration.py") + [
        "--in", str(delogo),
        "--out", str(paths["narrated_video"]),
        "--script-json", str(script),
        "--voice", args.voice,
        "--force-tts",
    ]
    if args.no_bgm:
        cmd.append("--no-bgm")
    if args.no_subtitles:
        cmd.append("--no-subtitles")
    if args.allow_synth_bgm:
        cmd.append("--allow-synth-bgm")
    if args.bgm:
        cmd += ["--bgm", str(Path(args.bgm).expanduser().resolve())]
    return run_stage("add_narration", cmd)


# --- stage 7: upload ---------------------------------------------------------

def stage_upload(args: argparse.Namespace, video: Path, script: Path, extra_desc: str) -> dict | None:
    """Run upload_youtube as a private draft (or dry-run); return its result.

    Returns None when uploading is fully suppressed via --no-upload (without
    --dry-run), so the pipeline still stops cleanly at a local final video.
    ``extra_desc`` (e.g. BGM attribution) is appended to the description.
    """
    if args.no_upload and not args.dry_run:
        log("[upload] skipped (--no-upload); final video stays local")
        return None
    cmd = py("upload_youtube.py") + [
        "--in", str(video),
        "--script-json", str(script),
        "--privacy", args.privacy,
    ]
    if extra_desc:
        cmd += ["--extra-description", extra_desc]
    cmd += _upload_auth_args(args)
    if args.dry_run:
        cmd.append("--dry-run")
    return run_stage("upload_youtube", cmd)


def _upload_auth_args(args: argparse.Namespace) -> list[str]:
    """Append client-secret/token auth flags only when the user provided them."""
    extra: list[str] = []
    if args.client_secret:
        extra += ["--client-secret", str(Path(args.client_secret).expanduser().resolve())]
    if args.token:
        extra += ["--token", str(Path(args.token).expanduser())]
    return extra


# --- url-ad stages -----------------------------------------------------------

def _is_vertical(aspect_ratio: str) -> bool:
    return aspect_ratio.replace(" ", "").lower() in ("9:16", "9x16", "vertical")


def stage_ingest(args: argparse.Namespace, paths: dict[str, Path]) -> Path:
    """url-ad Stage 0: ingest the URL into page_facts.json (or adopt a supplied one)."""
    dest = paths["page_facts"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if args.page_facts_json.strip():
        src = Path(args.page_facts_json).expanduser().resolve()
        if not src.is_file():
            raise SystemExit(f"--page-facts-json not found: {src}")
        if src != dest:
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        log(f"[ingest_url] using supplied page facts {src}")
        return dest
    if not args.url.strip():
        raise SystemExit("--mode url-ad requires --url (or --page-facts-json)")
    cmd = py("ingest_url.py") + [
        "--url", args.url.strip(),
        "--out", str(dest),
        "--target-format", "vertical" if _is_vertical(args.aspect_ratio) else "horizontal",
        "--session", args.session,
        "--capture-mode", "launch",  # public page: fresh agent browser, no attach
        "--max-shots", "8",  # more scroll captures -> shots can track the narration
    ]
    run_stage("ingest_url", cmd)
    return dest


def _urlad_idea_storyboard(page_facts: dict, paths: dict[str, Path]) -> Path:
    """Derive the minimal idea + storyboard write_script needs from page facts."""
    title = str(page_facts.get("title") or page_facts.get("brand") or "product").strip()
    idea_file = write_idea_file({"title": title, "metric": ""}, paths["idea"])
    # Short-form: one scene per top value prop (cap 5), NOT every feature, so the
    # narration stays ~30-45s and the shots can track it. Features still ground
    # the script via page_facts; they just don't each spawn a scene.
    items = [str(x).strip() for x in (page_facts.get("value_props") or []) if str(x).strip()][:5] or [title]
    scenes = [
        {"n": i, "beat": "", "visual": item, "camera": "", "on_screen_text": item}
        for i, item in enumerate(items, start=1)
    ]
    sb_dir = paths["storyboard_dir"]
    sb_dir.mkdir(parents=True, exist_ok=True)
    (sb_dir / "storyboard.json").write_text(
        json.dumps({"scenes": scenes, "screenshots": list(page_facts.get("screenshots") or [])},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return idea_file


def _estimate_narration_seconds(script: Path) -> float:
    """Rough total length from the narration char count (Korean ~5.5 chars/s)."""
    try:
        data = json.loads(Path(script).read_text(encoding="utf-8"))
        chars = len(str(data.get("narration_ko") or "").strip())
    except (OSError, json.JSONDecodeError):
        chars = 0
    return max(8.0, chars / 5.5)


def stage_visuals_slideshow(args: argparse.Namespace, script: Path, paths: dict[str, Path]) -> Path:
    """url-ad visuals: Ken-Burns slideshow over the captured real-page screenshots."""
    shots_dir = paths["page_facts"].parent / "page_facts_shots"
    if not sorted(shots_dir.glob("scene_*.png")):
        raise SystemExit(
            f"url-ad: no page screenshots in {shots_dir}; cannot build visuals"
        )
    width, height = (1080, 1920) if _is_vertical(args.aspect_ratio) else (1920, 1080)
    cmd = py("build_slideshow.py") + [
        "--storyboard-dir", str(shots_dir),
        "--duration", f"{_estimate_narration_seconds(script):.2f}",
        "--out", str(paths["raw_video"]),
        "--width", str(width),
        "--height", str(height),
    ]
    run_stage("build_slideshow", cmd)
    return paths["raw_video"]


# --- manifest ----------------------------------------------------------------

def build_manifest(args: argparse.Namespace, ctx: dict) -> dict:
    """Assemble the run manifest recording every choice and artifact path."""
    upload = ctx.get("upload") or {}
    delogo = ctx.get("delogo") or {}
    narration = ctx.get("narration") or {}
    return {
        "ok": True,
        "dry_run": args.dry_run,
        "topic": args.topic,
        "idea_index": args.idea_index,
        "idea": ctx.get("idea"),
        "ideas_json": _s(ctx.get("ideas")),
        "storyboard_dir": _s(ctx.get("storyboard_dir")),
        "script_json": _s(ctx.get("script")),
        "raw_video": _s(ctx.get("raw_video")),
        "delogo": {"video": _s(ctx.get("delogo_video")), "box": delogo.get("box")},
        "narration": _narration_info(args, narration),
        "final_video": _s(ctx.get("final_video")),
        "youtube": _youtube_info(args, upload),
        "stopped_for": "human-publish",
    }


def _narration_info(args: argparse.Namespace, narration: dict) -> dict:
    return {
        "voice": args.voice,
        "voice_name": narration.get("voice_name"),
        "tts": narration.get("tts"),
        "wav": narration.get("wav"),
        "bgm": narration.get("bgm"),
        "subtitles": narration.get("subtitles"),
        "credits": narration.get("credits"),
    }


def _bgm_attribution(narration: dict) -> str:
    """Extract the BGM attribution line from a narration result, or empty string."""
    bgm = narration.get("bgm") or {}
    attribution = bgm.get("attribution") if isinstance(bgm, dict) else None
    return f"Background music: {attribution}" if attribution else ""


def _youtube_info(args: argparse.Namespace, upload: dict) -> dict:
    return {
        "privacy": args.privacy,
        "uploaded": bool(upload.get("video_id")),
        "dry_run": bool(upload.get("dry_run")),
        "video_id": upload.get("video_id"),
        "watch_url": upload.get("watch_url"),
        "studio_url": upload.get("studio_url"),
    }


def _s(value: object) -> str | None:
    """Stringify a path-like value, or pass through None."""
    return str(value) if value is not None else None


def write_manifest(manifest: dict, path: Path) -> Path:
    """Persist the manifest JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --- argument parsing --------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    _add_core_args(parser)
    _add_pipeline_args(parser)
    _add_upload_args(parser)
    _add_skip_args(parser)
    return parser.parse_args()


def _add_core_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode", choices=["idea-video", "url-ad"], default="idea-video",
        help="workflow: idea-video (Studio/topic -> draft) or url-ad (URL -> "
             "grounded marketing video). product-ad uses generate_commercial.py.",
    )
    parser.add_argument("--url", default="", help="url-ad: website/product page URL to ingest")
    parser.add_argument(
        "--page-facts-json", default="",
        help="url-ad: reuse a supplied page_facts.json (skips the live ingest)",
    )
    parser.add_argument("--topic", default="", help="synthesize ideas around this topic instead of scraping")
    parser.add_argument("--idea-index", type=int, default=0, help="0-based idea to use from the harvest")
    parser.add_argument("--scenes", type=int, default=6, help="storyboard scene count")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="run output directory")


def _add_pipeline_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--flow-project-url", default=DEFAULT_FLOW_URL, help="Google Flow project URL")
    parser.add_argument("--channel-url", default=DEFAULT_FEED, help="Studio inspiration feed URL")
    parser.add_argument("--voice", default="F1", help="Supertonic voice id (default F1/Mina)")
    parser.add_argument("--duration", type=int, default=8, help="seconds per scene/clip")
    parser.add_argument("--aspect-ratio", default="16:9", help="video aspect ratio")
    parser.add_argument("--dry-run", action="store_true", help="skip Flow submit and real upload")
    parser.add_argument("--session", default="vya", help="single Playwright agent session for all browser stages")
    parser.add_argument("--no-attach", action="store_true", help="reuse an already-attached browser session")
    parser.add_argument("--no-bgm", action="store_true", help="Stage 6: disable background music")
    parser.add_argument("--no-subtitles", action="store_true", help="Stage 6: disable key-sentence captions")
    parser.add_argument("--bgm", help="Stage 6: explicit BGM track path (overrides mood resolution)")
    parser.add_argument(
        "--allow-synth-bgm", action="store_true",
        help="Stage 6: permit the synthesized CC0 ambient pad fallback when no real "
             "BGM source resolves; without it, BGM-on runs hard-stop instead of "
             "silently degrading to synth (real generation by default)",
    )


def _add_upload_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--privacy",
        choices=["private", "unlisted", "public"],
        default="private",
        help="upload privacy (default private; pipeline never auto-publishes)",
    )
    parser.add_argument("--client-secret", help="OAuth client_secret JSON path for upload")
    parser.add_argument("--token", help="token cache path (default in upload script)")
    parser.add_argument("--no-upload", action="store_true", help="stop before upload; keep final video local")


def _add_skip_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--skip-harvest", action="store_true", help="reuse an existing ideas file")
    parser.add_argument("--ideas-json", help="ideas JSON to reuse with --skip-harvest")
    parser.add_argument("--skip-storyboard", action="store_true", help="reuse an existing storyboard dir")
    parser.add_argument("--skip-video", action="store_true", help="reuse a supplied --video as the raw video")
    parser.add_argument("--video", help="supplied MP4 (placeholder for dry-run or with --skip-video)")


# --- run paths ---------------------------------------------------------------

def build_paths(out_dir: Path, mode: str = "idea-video") -> dict[str, Path]:
    """Resolve every artifact path under the run output directory."""
    paths = {
        "ideas": out_dir / "ideas.json",
        "idea": out_dir / "chosen_idea.json",
        "storyboard_dir": out_dir / "storyboard",
        "script": out_dir / "script.json",
        "raw_video": out_dir / "raw_flow.mp4",
        "delogo_video": out_dir / "delogo.mp4",
        "narrated_video": out_dir / "narrated.mp4",
        "manifest": out_dir / "manifest.json",
    }
    if mode == "url-ad":
        paths["page_facts"] = out_dir / "page_facts.json"
    return paths


# --- orchestration -----------------------------------------------------------

def run_pipeline(args: argparse.Namespace, paths: dict[str, Path]) -> dict:
    """Dispatch to the workflow pipeline by --mode (default idea-video)."""
    if getattr(args, "mode", "idea-video") == "url-ad":
        return run_pipeline_urlad(args, paths)
    return run_pipeline_idea_video(args, paths)


def run_pipeline_urlad(args: argparse.Namespace, paths: dict[str, Path]) -> dict:
    """url-ad: URL -> grounded script -> real-page slideshow -> narration -> upload.

    Reuses the shared stages: write_script (grounded via page_facts),
    build_slideshow (over the captured screenshots), add_narration, upload. No
    AI storyboard and no Flow/delogo — the real page IS the visual.
    """
    total = 5
    stage_header(1, total, "ingest_url")
    page_facts_path = stage_ingest(args, paths)
    gate("ingest_url", lambda: stage_gates.gate_page_facts(page_facts_path))
    page_facts = json.loads(page_facts_path.read_text(encoding="utf-8"))
    idea_file = _urlad_idea_storyboard(page_facts, paths)
    log(f"[idea] url-ad target: {page_facts.get('title', '')!r}")

    stage_header(2, total, "write_script")
    script = stage_script(args, idea_file, paths)
    gate("write_script", lambda: stage_gates.gate_script(script))

    stage_header(3, total, "build_slideshow")
    raw = stage_visuals_slideshow(args, script, paths)
    gate("build_slideshow", lambda: stage_gates.gate_video(raw, label="slideshow"))

    stage_header(4, total, "add_narration")
    narration = stage_narration(args, raw, script, paths)
    gate("add_narration", lambda: stage_gates.gate_narration(paths["narrated_video"]))
    final_video = paths["narrated_video"].resolve()

    if getattr(args, "no_upload", False):
        log(f"[upload] skipped (--no-upload); final video: {final_video}")
        upload = None
    else:
        stage_header(5, total, "upload_youtube")
        upload = stage_upload(args, final_video, script, _bgm_attribution(narration))

    return {
        "ideas": None, "idea": page_facts, "storyboard_dir": paths["storyboard_dir"],
        "script": script, "raw_video": raw, "delogo": {}, "delogo_video": None,
        "narration": narration, "final_video": final_video, "upload": upload,
        "page_facts": str(page_facts_path),
    }


def run_pipeline_idea_video(args: argparse.Namespace, paths: dict[str, Path]) -> dict:
    """Execute all stages in order, returning the assembled context dict."""
    total = 7
    stage_header(1, total, "harvest_ideas")
    ideas = stage_harvest(args, paths)
    gate("harvest_ideas", lambda: stage_gates.gate_ideas(ideas, min_count=args.idea_index + 1))
    idea = select_idea(ideas, args.idea_index)
    idea_file = write_idea_file(idea, paths["idea"])
    log(f"[idea] chosen: {idea.get('title', '')!r}")

    stage_header(2, total, "make_storyboard")
    storyboard_dir = stage_storyboard(args, ideas, paths)
    gate("make_storyboard", lambda: stage_gates.gate_storyboard(storyboard_dir, min_scenes=1))

    stage_header(3, total, "write_script")
    script = stage_script(args, idea_file, paths)
    gate("write_script", lambda: stage_gates.gate_script(script))

    stage_header(4, total, "generate_video")
    raw = stage_video(args, script, paths)
    gate("generate_video", lambda: stage_gates.gate_video(raw, label="raw_video"))

    stage_header(5, total, "remove_logo")
    delogo = stage_delogo(raw, paths)
    gate("remove_logo", lambda: stage_gates.gate_video(paths["delogo_video"], label="delogo"))

    stage_header(6, total, "add_narration")
    narration = stage_narration(args, paths["delogo_video"], script, paths)
    # Gate the known output path (not narration["out"]) so a malformed stage
    # result still yields a clean GATE FAILED rather than a KeyError.
    gate("add_narration", lambda: stage_gates.gate_narration(paths["narrated_video"]))
    final_video = paths["narrated_video"].resolve()

    stage_header(7, total, "upload_youtube")
    upload = stage_upload(args, final_video, script, _bgm_attribution(narration))

    return {
        "ideas": ideas, "idea": idea, "storyboard_dir": storyboard_dir,
        "script": script, "raw_video": raw, "delogo": delogo,
        "delogo_video": paths["delogo_video"], "narration": narration,
        "final_video": final_video, "upload": upload,
    }


def print_summary(manifest: dict, manifest_path: Path) -> None:
    """Print a human-facing closing summary to stderr."""
    yt = manifest["youtube"]
    log("")
    log("=== pipeline complete (stopped at the private draft) ===")
    log(f"manifest:     {manifest_path}")
    log(f"final video:  {manifest['final_video']}")
    if yt.get("uploaded"):
        log(f"YouTube draft (PRIVATE): {yt['studio_url']}")
        log("NEXT (human step): open the draft in YouTube Studio and flip private -> public.")
    elif yt.get("dry_run"):
        log("upload was a DRY RUN; nothing was uploaded.")
    else:
        log("upload skipped; the final video is local only.")


def main() -> int:
    args = parse_args()
    if args.mode == "url-ad" and not (args.url.strip() or args.page_facts_json.strip()):
        raise SystemExit("--mode url-ad requires --url (or --page-facts-json)")
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = build_paths(out_dir, args.mode)
    ctx = run_pipeline(args, paths)
    manifest = build_manifest(args, ctx)
    manifest_path = write_manifest(manifest, paths["manifest"])
    print_summary(manifest, manifest_path)
    studio_url = manifest["youtube"].get("studio_url")
    print(json.dumps(
        {"ok": True, "manifest": str(manifest_path),
         "studio_url": studio_url, "stopped_for": "human-publish"},
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
