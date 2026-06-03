#!/usr/bin/env python3
"""Stage 2 - expand a chosen idea into scene beats + one storyboard image per scene.

Reads ideas.json (Stage 1 output), picks one idea, asks codex (ChatGPT plan, no
API key) for an N-scene JSON breakdown, then renders one storyboard PNG per scene
via the gpt-image-2 skill's gen.sh. Prints exactly one JSON object to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

GEN_SH = Path(os.path.expanduser("~/.claude/skills/gpt-image-2/scripts/gen.sh"))


def log(message: str) -> None:
    """Route all human/progress output to stderr; stdout is reserved for the JSON."""
    print(message, file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idea-json", default="ideas.json", help="Stage 1 ideas file")
    parser.add_argument("--idea-index", type=int, default=0, help="0-based idea to use")
    parser.add_argument("--idea-title", default="", help="match idea by title (overrides index)")
    parser.add_argument("--scenes", type=int, default=6, help="number of scene beats")
    parser.add_argument("--out-dir", default="storyboard", help="output directory")
    parser.add_argument("--aspect", default="16:9", help="aspect ratio hint for image prompts")
    parser.add_argument(
        "--style",
        default="cinematic, consistent character and palette, vertical-friendly",
        help="style suffix appended to every image prompt for continuity",
    )
    parser.add_argument("--codex", default="codex", help="codex binary name or path")
    return parser.parse_args()


def extract_json(text: str) -> Any:
    """Return the first balanced top-level JSON array/object found in text.

    codex streams reasoning/prose around the answer; we scan for the first '['
    or '{', then walk forward tracking brackets and string state until balanced.
    """
    start = _first_json_start(text)
    if start < 0:
        raise ValueError("no JSON array/object found in codex output")
    snippet = _scan_balanced(text, start)
    return json.loads(snippet)


def _first_json_start(text: str) -> int:
    candidates = [pos for pos in (text.find("["), text.find("{")) if pos >= 0]
    return min(candidates) if candidates else -1


def _scan_balanced(text: str, start: int) -> str:
    open_ch = text[start]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError("unbalanced JSON in codex output")


def load_idea(idea_json: Path, index: int, title: str) -> dict[str, Any]:
    """Load the chosen idea dict; title match (case-insensitive) wins over index."""
    if not idea_json.exists():
        raise SystemExit(f"ideas file not found: {idea_json}")
    data = json.loads(idea_json.read_text(encoding="utf-8"))
    ideas = data.get("ideas", data) if isinstance(data, dict) else data
    if not isinstance(ideas, list) or not ideas:
        raise SystemExit(f"no ideas array in {idea_json}")
    normalized = [_as_idea(item) for item in ideas]
    if title:
        return _match_title(normalized, title)
    if index < 0 or index >= len(normalized):
        raise SystemExit(f"idea-index {index} out of range (have {len(normalized)})")
    return normalized[index]


def _as_idea(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    return {"title": str(item)}


def _match_title(ideas: list[dict[str, Any]], title: str) -> dict[str, Any]:
    needle = title.strip().lower()
    for idea in ideas:
        if str(idea.get("title", "")).strip().lower() == needle:
            return idea
    for idea in ideas:
        if needle in str(idea.get("title", "")).strip().lower():
            return idea
    raise SystemExit(f"no idea matched title: {title!r}")


def scene_schema(scenes: int) -> dict[str, Any]:
    """JSON Schema enforcing the exact scene-list shape codex must return."""
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["n", "beat", "visual", "camera", "on_screen_text"],
        "properties": {
            "n": {"type": "integer"},
            "beat": {"type": "string"},
            "visual": {"type": "string"},
            "camera": {"type": "string"},
            "on_screen_text": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["scenes"],
        "properties": {
            "scenes": {"type": "array", "minItems": scenes, "maxItems": scenes, "items": item},
        },
    }


def scene_prompt(idea: dict[str, Any], scenes: int, style: str) -> str:
    title = str(idea.get("title", "")).strip()
    metric = str(idea.get("metric", "")).strip()
    context = f" Audience signal: {metric}." if metric else ""
    return (
        f"You are a YouTube short-form video director. Idea: {title!r}.{context}\n"
        f"Break this into exactly {scenes} sequential scene beats for a vertical-friendly "
        f"video. Return ONLY a JSON object: {{\"scenes\": [ ... ]}} with {scenes} items. "
        "Each item has: n (1-based int), beat (the story function this scene serves), "
        "visual (a concrete image-generation prompt describing the frame), camera (shot "
        "and movement), on_screen_text (short Korean caption, may be empty). Keep one "
        f"consistent main character, palette and world across all scenes. Visual style: {style}."
    )


def run_codex_scenes(args: argparse.Namespace, idea: dict[str, Any]) -> list[dict[str, Any]]:
    """Call codex with an output schema; fall back to extract_json on the raw text."""
    prompt = scene_prompt(idea, args.scenes, args.style)
    with tempfile.TemporaryDirectory() as tmp:
        schema_path = Path(tmp) / "schema.json"
        answer_path = Path(tmp) / "answer.json"
        schema_path.write_text(json.dumps(scene_schema(args.scenes)), encoding="utf-8")
        text = _invoke_codex(args.codex, prompt, schema_path, answer_path)
    parsed = _parse_scene_payload(text)
    scenes = parsed["scenes"] if isinstance(parsed, dict) else parsed
    return _normalize_scenes(scenes, args.scenes)


def _invoke_codex(codex: str, prompt: str, schema: Path, answer: Path) -> str:
    cmd = [
        codex, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
        "--color", "never", "--output-schema", str(schema), "-o", str(answer),
    ]
    log("+ codex exec (scene breakdown)")
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"codex scene generation failed (exit {proc.returncode}): {proc.stderr.strip()}")
    if answer.exists() and answer.read_text(encoding="utf-8").strip():
        return answer.read_text(encoding="utf-8")
    return proc.stdout


def _parse_scene_payload(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return extract_json(text)


def _normalize_scenes(scenes: Any, expected: int) -> list[dict[str, Any]]:
    if not isinstance(scenes, list) or not scenes:
        raise SystemExit("codex returned no scenes")
    result: list[dict[str, Any]] = []
    for i, raw in enumerate(scenes[:expected], start=1):
        item = raw if isinstance(raw, dict) else {"visual": str(raw)}
        result.append(
            {
                "n": int(item.get("n", i)),
                "beat": str(item.get("beat", "")),
                "visual": str(item.get("visual", "")),
                "camera": str(item.get("camera", "")),
                "on_screen_text": str(item.get("on_screen_text", "")),
            }
        )
    return result


def image_prompt(scene: dict[str, Any], aspect: str, style: str) -> str:
    visual = scene.get("visual", "").strip()
    camera = scene.get("camera", "").strip()
    camera_clause = f" Camera: {camera}." if camera else ""
    return f"{visual}{camera_clause} Aspect ratio {aspect}. Style: {style}."


def render_scene_image(scene: dict[str, Any], out_dir: Path, aspect: str, style: str) -> str | None:
    """Render one storyboard PNG; return its path, or None if generation failed."""
    out_path = out_dir / f"scene_{int(scene['n']):02d}.png"
    prompt = image_prompt(scene, aspect, style)
    cmd = ["bash", str(GEN_SH), "--prompt", prompt, "--out", str(out_path), "--timeout-sec", "300"]
    log(f"+ gen.sh scene {scene['n']:02d}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        log(f"  scene {scene['n']:02d} image failed (exit {proc.returncode}): {proc.stderr.strip()[:200]}")
        return None
    if not out_path.exists():
        log(f"  scene {scene['n']:02d} produced no file at {out_path}")
        return None
    return str(out_path)


def render_all(scenes: list[dict[str, Any]], out_dir: Path, aspect: str, style: str) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for scene in scenes:
        image_path = render_scene_image(scene, out_dir, aspect, style)
        rendered.append({**scene, "image_path": image_path})
    return rendered


def main() -> int:
    args = parse_args()
    if not GEN_SH.exists():
        raise SystemExit(f"gpt-image-2 gen.sh not found: {GEN_SH}")
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    idea = load_idea(Path(args.idea_json).resolve(), args.idea_index, args.idea_title)
    log(f"idea: {idea.get('title', '')!r}")
    scenes = run_codex_scenes(args, idea)
    rendered = render_all(scenes, out_dir, args.aspect, args.style)
    result = {"ok": True, "idea": idea, "scenes": rendered}
    (out_dir / "storyboard.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
