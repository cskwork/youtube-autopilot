#!/usr/bin/env python3
"""Stage 3 - narration, Flow video prompt, and YouTube metadata via codex."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# JSON Schema the codex final message must satisfy. youtube.category is a
# YouTube category id string ("22" = People & Blogs) kept as text on purpose.
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "narration_ko", "flow_prompt", "scene_prompts",
        "bgm_mood", "key_sentences", "youtube",
    ],
    "properties": {
        "narration_ko": {"type": "string"},
        "flow_prompt": {"type": "string"},
        "scene_prompts": {"type": "array", "items": {"type": "string"}},
        "bgm_mood": {"type": "string"},
        "key_sentences": {"type": "array", "items": {"type": "string"}},
        "youtube": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "description", "tags", "category"],
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "category": {"type": "string"},
            },
        },
    },
}

REQUIRED_TOP = (
    "narration_ko", "flow_prompt", "scene_prompts",
    "bgm_mood", "key_sentences", "youtube",
)
REQUIRED_YT = ("title", "description", "tags", "category")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idea-json", required=True, help="Stage 1 idea JSON file")
    parser.add_argument(
        "--storyboard-json",
        default="storyboard/storyboard.json",
        help="Stage 2 storyboard JSON file",
    )
    parser.add_argument("--out", default="script.json", help="output script JSON path")
    parser.add_argument("--lang", default="ko", help="narration language code")
    parser.add_argument("--duration", type=int, default=8, help="seconds per scene")
    parser.add_argument(
        "--page-facts-json", default="",
        help="url-ad: page_facts.json to ground the script in (hook->USP->CTA)",
    )
    parser.add_argument("--aspect-ratio", default="16:9", help="target aspect ratio (9:16 or 16:9)")
    parser.add_argument("--codex", default="codex", help="codex CLI command")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    if not path.exists():
        raise SystemExit(f"missing input file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}") from exc


def scene_list(storyboard: Any) -> list[Any]:
    """Pull the scene array from a storyboard dict or accept a bare list."""
    if isinstance(storyboard, list):
        return storyboard
    if isinstance(storyboard, dict):
        for key in ("scenes", "storyboard", "shots", "panels"):
            value = storyboard.get(key)
            if isinstance(value, list):
                return value
    return []


def _aspect_note(aspect_ratio: str) -> str:
    """One-line format hint so codex paces the narration for the target frame."""
    if aspect_ratio.replace(" ", "").lower() in ("9:16", "9x16", "vertical"):
        return ("Target format: 9:16 VERTICAL (Shorts/Reels/TikTok). Keep it "
                "punchy and fast; front-load the hook.\n")
    return f"Target format: {aspect_ratio} landscape.\n"


def _grounding_block(page_facts: Any) -> str:
    """Marketing grounding for url-ad: facts-only + hook -> USP -> CTA structure."""
    pf = page_facts if isinstance(page_facts, dict) else {}
    title = str(pf.get("title") or "").strip()
    brand = str(pf.get("brand") or title or "the product").strip()
    url = str(pf.get("url") or "").strip()
    props = [str(x).strip() for x in (pf.get("value_props") or []) if str(x).strip()]
    feats = [str(x).strip() for x in (pf.get("features") or []) if str(x).strip()]
    cta = str(pf.get("cta_text") or "").strip()
    parts = [
        "\n=== MARKETING GROUNDING (url-ad) ===",
        f"This is a marketing/demo video for: {brand}" + (f" - {title}" if title else ""),
    ]
    if url:
        parts.append(f"Source page: {url}")
    parts.append("Value propositions: " + json.dumps(props, ensure_ascii=False))
    parts.append("Features: " + json.dumps(feats, ensure_ascii=False))
    if cta:
        parts.append(f"Call to action: {cta}")
    cta_clause = f': "{cta}"' if cta else "."
    parts.append(
        "\nGROUND THE SCRIPT IN THESE FACTS ONLY. Do not invent features, prices, "
        "claims, or product names that are not listed above.\n"
        "Keep the ENTIRE narration SHORT for a vertical ad: about 30-45 seconds of "
        "speech. Cover only the strongest 3-4 value propositions; do NOT enumerate "
        "every feature or menu item.\n"
        "Structure narration as HOOK -> UNIQUE SELLING POINTS -> CALL TO ACTION:\n"
        "1. First ~3s: state the core value proposition (a viewer who sees only "
        "the opening still gets the point).\n"
        "2. Within ~6s: land an explicit hook drawn from the value propositions.\n"
        "3. Middle: showcase the unique selling points / features above.\n"
        f"4. End with a clear call to action{cta_clause}\n"
        "Include the call-to-action sentence in key_sentences."
    )
    return "\n".join(parts) + "\n"


def build_prompt(
    idea: Any, storyboard: Any, scenes: list[Any], lang: str, duration: int,
    page_facts: Any = None, aspect_ratio: str = "16:9",
) -> str:
    count = max(len(scenes), 1)
    target_seconds = duration * count
    idea_text = json.dumps(idea, ensure_ascii=False, indent=2)
    story_text = json.dumps(storyboard, ensure_ascii=False, indent=2)
    grounding = _grounding_block(page_facts) if page_facts else ""
    return (
        "You are a YouTube short-form director and Korean copywriter.\n"
        "Given a video IDEA and a STORYBOARD, produce a production script as "
        "STRICT JSON only (no prose, no markdown fences).\n\n"
        f"Language for narration: {lang}.\n"
        f"Scene count: {count}. Each scene runs about {duration} seconds, so "
        f"narration must be paced to roughly {target_seconds} seconds total.\n"
        f"{_aspect_note(aspect_ratio)}"
        f"{grounding}\n"
        "Output keys and rules:\n"
        '- "narration_ko": one spoken script using short natural Hangul '
        "sentences that read cleanly for TTS; no English, no emoji, no stage "
        "directions, no numbered lists.\n"
        '- "flow_prompt": ONE consolidated cinematic text-to-video prompt that '
        "references the storyboard scenes and visual style; do NOT include any "
        "on-screen text, fake logos, or watermarks.\n"
        '- "scene_prompts": an array with exactly one cinematic Flow prompt per '
        f"storyboard scene ({count} items), in scene order.\n"
        '- "bgm_mood": short English mood/genre keywords for background-music '
        'search (e.g., "calm uplifting ambient corporate"); no Korean, no '
        "punctuation lists.\n"
        '- "key_sentences": an array of 2-4 of the MOST important narration '
        "sentences, copied VERBATIM from narration_ko (exact same characters), "
        "to be shown as on-screen captions.\n"
        '- "youtube": object with "title" (<=100 characters), "description" '
        "(multi-line, starts with a hook line then chapter lines), "
        '"tags" (array of short keyword strings), and "category" set to "22".\n\n'
        f"IDEA:\n{idea_text}\n\nSTORYBOARD:\n{story_text}\n"
    )


def codex_text(codex_cmd: str, prompt: str) -> str:
    """Run codex text gen with an enforced JSON schema, return final message."""
    base = shlex.split(codex_cmd)
    with tempfile.TemporaryDirectory(prefix="write_script_") as tmp:
        schema_path = Path(tmp) / "schema.json"
        answer_path = Path(tmp) / "answer.json"
        schema_path.write_text(
            json.dumps(OUTPUT_SCHEMA, ensure_ascii=False), encoding="utf-8"
        )
        cmd = base + [
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "-o",
            str(answer_path),
        ]
        print("+", shlex.join(cmd), file=sys.stderr)
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, check=False
        )
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        return _final_message(proc, answer_path)


def _final_message(proc: subprocess.CompletedProcess[str], answer_path: Path) -> str:
    """Prefer the -o file; fall back to stdout tail; fail loud on empty."""
    if answer_path.exists():
        text = answer_path.read_text(encoding="utf-8").strip()
        if text:
            return text
    stdout = (proc.stdout or "").strip()
    if proc.returncode != 0 and not stdout:
        raise SystemExit(f"codex exec failed (exit {proc.returncode})")
    if not stdout:
        raise SystemExit("codex produced no output")
    return stdout


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from raw text, tolerating fences and log noise."""
    candidate = _strip_fence(text.strip())
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = json.loads(_outermost_object(candidate))
    if not isinstance(parsed, dict):
        raise SystemExit("codex output was not a JSON object")
    return parsed


def _strip_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    body = text[3:]
    if body[:4].lower() == "json":
        body = body[4:]
    end = body.rfind("```")
    return body[:end].strip() if end != -1 else body.strip()


def _outermost_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise SystemExit("no JSON object found in codex output")
    return text[start : end + 1]


def validate(result: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_TOP if key not in result]
    if missing:
        raise SystemExit(f"missing required keys: {', '.join(missing)}")
    if not isinstance(result["scene_prompts"], list):
        raise SystemExit("scene_prompts must be an array")
    if not isinstance(result["bgm_mood"], str) or not result["bgm_mood"].strip():
        raise SystemExit("bgm_mood must be a non-empty string")
    if not isinstance(result["key_sentences"], list):
        raise SystemExit("key_sentences must be an array")
    youtube = result["youtube"]
    if not isinstance(youtube, dict):
        raise SystemExit("youtube must be an object")
    missing_yt = [key for key in REQUIRED_YT if key not in youtube]
    if missing_yt:
        raise SystemExit(f"missing youtube keys: {', '.join(missing_yt)}")
    if not isinstance(youtube["tags"], list):
        raise SystemExit("youtube.tags must be an array")
    title = youtube["title"]
    if not isinstance(title, str) or len(title) > 100:
        raise SystemExit("youtube.title must be a string <= 100 characters")


def main() -> int:
    args = parse_args()
    idea = load_json(Path(args.idea_json).resolve())
    storyboard = load_json(Path(args.storyboard_json).resolve())
    scenes = scene_list(storyboard)
    page_facts = None
    if args.page_facts_json.strip():
        page_facts = load_json(Path(args.page_facts_json).resolve())
    prompt = build_prompt(
        idea, storyboard, scenes, args.lang, args.duration,
        page_facts=page_facts, aspect_ratio=args.aspect_ratio,
    )
    raw = codex_text(args.codex, prompt)
    result = extract_json(raw)
    validate(result)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {"ok": True, "out": str(out_path), "scenes": len(scenes)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
