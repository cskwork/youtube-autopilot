#!/usr/bin/env python3
"""Stage 1 of youtube-autopilot: harvest top-N ranked video ideas.

Two modes:
  --topic "X"  -> skip scraping; ask codex to synthesize N ideas around X.
  (default)    -> attach to a logged-in Chrome, open the YouTube Studio
                  inspiration feed, scrape raw idea cards via the Playwright
                  agent CLI (run-code js/studio_inspiration.js), optionally
                  fall back to youtube.com trending, then ask codex to turn
                  the raw signal into N ranked idea objects.

On success prints exactly one JSON line to stdout:
  {"ok": true, "source": "studio|search|topic", "ideas": [...]}
All progress/log lines go to stderr. On failure raises SystemExit.

Reuses the attach / run-code subprocess pattern from google_flow_cli.py.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
JS = HERE / "js"
STUDIO_JS = JS / "studio_inspiration.js"

DEFAULT_FEED = (
    "https://studio.youtube.com/channel/YOUR_CHANNEL_ID"
    "/content/inspiration/feed"
)
TRENDING_URL = "https://www.youtube.com/feed/trending"


# --- logging -----------------------------------------------------------------

def log(message: str) -> None:
    """Write a progress line to stderr (stdout is reserved for the JSON result)."""
    print(message, file=sys.stderr, flush=True)


# --- Playwright agent CLI helpers (mirrors google_flow_cli.py) ---------------

def cli_base(args: argparse.Namespace) -> list[str]:
    return shlex.split(args.cli)


def cmd(args: argparse.Namespace, *parts: str, session: bool = True) -> list[str]:
    base = cli_base(args)
    if session:
        base.append(f"-s={args.session}")
    return [*base, *parts]


def run(args: argparse.Namespace, parts: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if args.npm_cache:
        env["npm_config_cache"] = args.npm_cache
    return subprocess.run(parts, env=env, capture_output=True, text=True)


def attach(args: argparse.Namespace) -> None:
    target = f"--cdp={args.cdp_endpoint}"
    proc = run(args, [*cli_base(args), "attach", target, f"--session={args.session}"])
    log(proc.stdout or "")
    if proc.returncode != 0:
        raise SystemExit(f"attach failed: {proc.stderr or proc.stdout}")


def goto(args: argparse.Namespace, url: str) -> None:
    run(args, cmd(args, "goto", url))
    time.sleep(2)


def run_code(args: argparse.Namespace, js_file: Path) -> dict:
    proc = run(args, cmd(args, "run-code", "--filename", str(js_file), "--raw"))
    return _json_result(proc.stdout, proc.stderr)


def _json_result(stdout: str | None, stderr: str | None) -> dict:
    out = (stdout or "").strip().strip('"').encode().decode("unicode_escape")
    try:
        return json.loads(out)
    except Exception:
        return {"ok": False, "rawstdout": stdout, "stderr": stderr}


# --- scraping ----------------------------------------------------------------

def scrape_with_retry(args: argparse.Namespace, label: str, attempts: int = 6, delay: float = 3.0) -> list[dict]:
    """Run the scraper repeatedly so a heavy Angular feed has time to render.

    Studio is virtualized and slow to paint after navigation, so a single pass
    often returns nothing. Retry until items appear or attempts run out.
    """
    last: dict = {}
    for n in range(attempts):
        result = run_code(args, STUDIO_JS)
        items = result.get("items") or []
        log(f"[{label} try {n + 1}/{attempts}] {json.dumps(_summary(result), ensure_ascii=False)}")
        if items:
            return items
        last = result
        time.sleep(delay)
    log(f"[{label}] no items after {attempts} tries; last={json.dumps(_summary(last), ensure_ascii=False)}")
    return []


def scrape_feed(args: argparse.Namespace) -> tuple[str, list[dict]]:
    """Scrape the Studio inspiration feed; fall back to trending search.

    Returns (source, items) where source is "studio" or "search".
    """
    goto(args, args.channel_url)
    items = scrape_with_retry(args, "studio")
    if items:
        return ("studio", items)
    if not args.fallback_search:
        return ("studio", [])
    log("[fallback] studio feed empty; trying youtube.com trending")
    goto(args, TRENDING_URL)
    return ("search", scrape_with_retry(args, "search"))


def _summary(result: dict) -> dict:
    return {
        "ok": result.get("ok"),
        "source": result.get("source"),
        "count": result.get("count"),
        "note": result.get("note"),
    }


# --- codex helpers -----------------------------------------------------------

def codex_base(args: argparse.Namespace) -> list[str]:
    return [
        *shlex.split(args.codex),
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
    ]


def codex_json(args: argparse.Namespace, prompt: str) -> dict:
    """Run codex on a prompt and parse the JSON object from its final message.

    Uses -o FILE so only the agent's final message is captured (no log noise).
    """
    with tempfile.TemporaryDirectory(prefix="harvest-codex-") as tmp:
        out_file = Path(tmp) / "answer.txt"
        parts = [*codex_base(args), "-o", str(out_file)]
        proc = subprocess.run(parts, input=prompt, capture_output=True, text=True)
        text = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
    if not text.strip():
        text = proc.stdout or ""
    if proc.returncode != 0 and not text.strip():
        raise SystemExit(f"codex failed (exit {proc.returncode}): {proc.stderr.strip()}")
    parsed = _extract_json(text)
    if parsed is None:
        raise SystemExit(f"codex returned no JSON object; raw tail: {text[-400:]!r}")
    return parsed


def _extract_json(text: str) -> dict | None:
    """Find the first balanced {...} JSON object in codex output and parse it.

    codex may wrap the answer in prose or ```json fences; this strips both.
    """
    cleaned = text.replace("```json", "").replace("```", "")
    start = cleaned.find("{")
    while start != -1:
        candidate = _balanced_object(cleaned, start)
        if candidate is not None:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        start = cleaned.find("{", start + 1)
    return None


def _balanced_object(text: str, start: int) -> str | None:
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


# --- prompt building ---------------------------------------------------------

def _idea_schema_note(limit: int) -> str:
    return (
        f"Return ONLY a JSON object with this exact shape (no prose, no fences):\n"
        f'{{"ideas": [{{"rank": 1, "title": "", "angle": "", "hook": "", '
        f'"keywords": ["", ""], "why": "", "target_length_sec": 60}}]}}\n'
        f"Produce exactly {limit} idea objects, ranked 1..{limit} by expected "
        f"audience demand (rank 1 = strongest). Write title/angle/hook/why in "
        f"natural Korean; keywords may mix Korean and English search terms. "
        f"target_length_sec is an integer number of seconds for a short-form "
        f"vertical video (typically 30-90)."
    )


def topic_prompt(topic: str, limit: int) -> str:
    return (
        f"You are a YouTube content strategist for a Korean channel. "
        f"Brainstorm {limit} distinct, high-potential short-form video ideas "
        f'centered on this topic: "{topic}".\n\n' + _idea_schema_note(limit)
    )


def signal_prompt(items: list[dict], source: str, limit: int) -> str:
    signal = json.dumps(items[:40], ensure_ascii=False, indent=2)
    origin = "YouTube Studio inspiration feed" if source == "studio" else "YouTube trending/search"
    return (
        f"You are a YouTube content strategist for a Korean channel. "
        f"Below is raw signal scraped from the {origin}: titles, metrics, and "
        f"keywords of currently popular or suggested content.\n\n"
        f"RAW SIGNAL:\n{signal}\n\n"
        f"Synthesize the best {limit} short-form video ideas inspired by this "
        f"signal. Adapt and improve on the trends; do not copy titles verbatim. "
        + _idea_schema_note(limit)
    )


# --- idea normalization ------------------------------------------------------

def normalize_ideas(parsed: dict, limit: int) -> list[dict]:
    raw = parsed.get("ideas")
    if not isinstance(raw, list) or not raw:
        raise SystemExit(f"codex produced no usable ideas: {parsed!r}")
    ideas = [_normalize_idea(item, i + 1) for i, item in enumerate(raw[:limit])]
    return ideas


def _normalize_idea(item: dict, rank: int) -> dict:
    if not isinstance(item, dict):
        item = {}
    keywords = item.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = [str(keywords)]
    length = item.get("target_length_sec", 60)
    try:
        length = int(length)
    except (TypeError, ValueError):
        length = 60
    return {
        "rank": int(item.get("rank", rank) or rank),
        "title": str(item.get("title", "")).strip(),
        "angle": str(item.get("angle", "")).strip(),
        "hook": str(item.get("hook", "")).strip(),
        "keywords": [str(k).strip() for k in keywords if str(k).strip()],
        "why": str(item.get("why", "")).strip(),
        "target_length_sec": length,
    }


# --- orchestration -----------------------------------------------------------

def harvest(args: argparse.Namespace) -> dict:
    if args.topic.strip():
        log(f"[mode] topic synthesis: {args.topic!r}")
        parsed = codex_json(args, topic_prompt(args.topic.strip(), args.limit))
        return {"source": "topic", "ideas": normalize_ideas(parsed, args.limit)}
    if not args.no_attach:
        attach(args)
    source, items = scrape_feed(args)
    log(f"[scrape] source={source} items={len(items)}")
    if not items:
        raise SystemExit(
            "no idea cards scraped (studio feed and fallback both empty); "
            "pass --topic to synthesize ideas without scraping"
        )
    parsed = codex_json(args, signal_prompt(items, source, args.limit))
    return {"source": source, "ideas": normalize_ideas(parsed, args.limit)}


def write_result(out_path: Path, payload: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--channel-url", default=DEFAULT_FEED, help="inspiration feed URL")
    p.add_argument("--out", default="ideas.json", help="output JSON path")
    p.add_argument("--limit", type=int, default=5, help="number of ideas to produce")
    p.add_argument(
        "--topic",
        default="",
        help="if set, skip scraping and synthesize ideas around this topic",
    )
    p.add_argument("--session", default="ytstudio")
    p.add_argument("--cli", default="npx @playwright/cli@latest")
    # Empty = use the system npm cache so this CLI install (and its session
    # daemon) matches the one used to attach. A custom cache pulls a different
    # @playwright/cli version that cannot see the attached session.
    p.add_argument("--npm-cache", default="")
    p.add_argument("--attach", choices=["cdp"], default="cdp")
    p.add_argument("--cdp-endpoint", default="chrome")
    p.add_argument("--no-attach", action="store_true", help="reuse an existing session")
    p.add_argument(
        "--fallback-search",
        dest="fallback_search",
        action="store_true",
        default=True,
        help="fall back to youtube.com trending when the feed is empty (default on)",
    )
    p.add_argument(
        "--no-fallback-search",
        dest="fallback_search",
        action="store_false",
        help="disable the youtube.com trending fallback",
    )
    p.add_argument("--codex", default="codex", help="codex CLI command")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = harvest(args)
    payload = {"ok": True, **result}
    write_result(Path(args.out).resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
