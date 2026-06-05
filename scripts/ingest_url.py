#!/usr/bin/env python3
"""url-ad Stage 0: ingest a website URL into grounded page facts.

Drives the SAME attached Chrome session used for Flow/Studio (see SKILL.md
<browser_attach>) to navigate the URL and pull Open Graph/meta + readable text +
viewport screenshots (js/fetch_url_artifacts.tmpl.js), then asks codex to distill
the raw extraction into marketing facts. Writes page_facts.json (the contract in
PAGE_FACTS_SCHEMA, verified by stage_gates.gate_page_facts) and the screenshots
as scene_*.png so build_slideshow.py / build_kenburns_clip.py can reuse them as
faithful B-roll.

Prints exactly one JSON line on stdout: {"ok": true, "out": <path>, "shots": N};
logs go to stderr. The live browser run is a human-approved step (it shells out
to npx @playwright/cli); the pure helpers below are unit-tested offline.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
JS = HERE / "js"


def _load_sibling(name: str):
    """Import a sibling scripts/ module by path (cwd-independent)."""
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


flow = _load_sibling("google_flow_cli")  # reuse attach/cmd/run/_json_result

# Documentation of the page_facts.json contract gate_page_facts verifies.
PAGE_FACTS_SCHEMA: dict[str, str] = {
    "url": "str (required) - the ingested page URL",
    "title": "str (required) - page/product title",
    "brand": "str - brand/company name",
    "value_props": "list[str] (required, >=1) - headline benefits -> USP slot",
    "features": "list[str] - concrete features mentioned on the page",
    "cta_text": "str (required) - call-to-action copy -> CTA slot",
    "cta_url": "str - call-to-action target URL",
    "brand_colors": "list[str] - hex colors for caption/theme accents",
    "screenshots": "list[str] - captured PNG paths -> faithful B-roll",
}

# JSON Schema codex must satisfy when distilling raw extraction into facts.
DISTILL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    # OpenAI strict structured output requires every property in `required`.
    "required": ["title", "brand", "value_props", "features", "cta_text", "cta_url", "brand_colors"],
    "properties": {
        "title": {"type": "string"},
        "brand": {"type": "string"},
        "value_props": {"type": "array", "items": {"type": "string"}},
        "features": {"type": "array", "items": {"type": "string"}},
        "cta_text": {"type": "string"},
        "cta_url": {"type": "string"},
        "brand_colors": {"type": "array", "items": {"type": "string"}},
    },
}

_VIEWPORTS = {
    "vertical": {"width": 1080, "height": 1920},
    "horizontal": {"width": 1920, "height": 1080},
}


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# --- pure helpers (unit-tested offline) --------------------------------------

def render_fetch_js(template: str, url: str, max_shots: int, viewport: dict) -> str:
    """Substitute the JSON-literal placeholders in fetch_url_artifacts.tmpl.js."""
    return (
        template.replace("__URL__", json.dumps(url, ensure_ascii=False))
        .replace("__MAX_SHOTS__", json.dumps(int(max_shots)))
        .replace("__VIEWPORT__", json.dumps(viewport))
    )


def write_screenshots(shots_b64: list[str], shots_dir: Path) -> list[str]:
    """Decode base64 viewport shots into scene_*.png; return the written paths."""
    shots_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for i, b64 in enumerate(shots_b64):
        if not b64:
            continue
        try:
            data = base64.b64decode(b64)
        except (ValueError, TypeError):
            continue
        if not data:
            continue
        path = shots_dir / f"scene_{i:02d}.png"
        path.write_bytes(data)
        paths.append(str(path))
    return paths


def parse_runcode_json(stdout: str | None) -> dict:
    """Parse the JSON object a run-code page function returned.

    The agent CLI prints the returned string with --raw; depending on version it
    is a bare JSON object or a JSON string literal wrapping one. Decode via
    json.loads (UTF-8 safe — never unicode_escape, which mangles Hangul) and peel
    one string layer if present.
    """
    s = (stdout or "").strip()
    for _ in range(2):
        try:
            value = json.loads(s)
        except json.JSONDecodeError:
            break
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            s = value
            continue
        break
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        return json.loads(s[start : end + 1])
    raise SystemExit(f"could not parse run-code output: {(stdout or '')[:200]!r}")


def build_distill_prompt(facts: dict) -> str:
    """Prompt codex to turn raw page extraction into marketing facts (facts-only)."""
    raw = json.dumps(facts, ensure_ascii=False, indent=2)[:8000]
    return (
        "You are a marketing analyst. From the RAW extraction of a product/landing "
        "page below, produce STRICT JSON only (no prose, no fences) describing the "
        "product's marketing facts. Use ONLY information present in the extraction; "
        "do not invent features, prices, or claims.\n\n"
        "Keys:\n"
        '- "title": the product/page title.\n'
        '- "brand": the brand or company name.\n'
        '- "value_props": 2-5 headline benefits, each a short phrase (the WHY, '
        "not menu labels).\n"
        '- "features": concrete capabilities or benefits named on the page; '
        "prefer real functionality over bare navigation labels; may be empty.\n"
        '- "cta_text": the primary call-to-action label (e.g. "Start free"). MUST '
        "be non-empty; if the page has no explicit CTA button, infer a short "
        "imperative call to action in the page's own language.\n"
        '- "cta_url": the call-to-action link if identifiable, else "".\n'
        '- "brand_colors": hex colors if identifiable, else [].\n\n'
        f"RAW EXTRACTION:\n{raw}\n"
    )


def assemble_page_facts(
    distilled: dict, raw_facts: dict, url: str, screenshots: list[str]
) -> dict:
    """Merge distilled facts with the URL + screenshots into the page_facts contract."""
    d = distilled if isinstance(distilled, dict) else {}
    raw = raw_facts if isinstance(raw_facts, dict) else {}
    title = str(d.get("title") or raw.get("title") or "").strip()
    return {
        "url": url or str(raw.get("url") or ""),
        "title": title,
        "brand": str(d.get("brand") or title).strip(),
        "value_props": [str(x).strip() for x in (d.get("value_props") or []) if str(x).strip()],
        "features": [str(x).strip() for x in (d.get("features") or []) if str(x).strip()],
        "cta_text": str(d.get("cta_text") or "").strip(),
        "cta_url": str(d.get("cta_url") or "").strip(),
        "brand_colors": [str(x).strip() for x in (d.get("brand_colors") or []) if str(x).strip()],
        "screenshots": list(screenshots),
    }


# --- browser fetch + codex distillation (live) -------------------------------

def _ensure_browser(args: argparse.Namespace) -> None:
    """Bootstrap the browser session: launch a fresh one (public URLs) or attach.

    Public pages (the url-ad default) need no logged-in session, so 'launch' opens
    a fresh agent browser (Chrome-for-Testing) — no attach to the user's Chrome.
    'attach' reuses the user's logged-in Chrome for authenticated pages.
    """
    if args.reuse_session:
        return
    if args.capture_mode == "attach":
        flow.attach(args)
    else:
        flow.run(args, flow.cmd(args, "open", args.url), capture=True)


def _close_browser(args: argparse.Namespace) -> None:
    """Close a browser we launched (never an attached or reused session)."""
    if args.capture_mode != "launch" or args.reuse_session:
        return
    try:
        flow.run(args, flow.cmd(args, "close"), capture=True)
    except Exception:  # noqa: BLE001 - best-effort teardown
        pass


def fetch_artifacts(args: argparse.Namespace) -> dict:
    """Bootstrap the browser and run the fetch JS; return {facts, shots}."""
    _ensure_browser(args)
    viewport = _VIEWPORTS.get(args.target_format, _VIEWPORTS["vertical"])
    template = (JS / "fetch_url_artifacts.tmpl.js").read_text(encoding="utf-8")
    js = render_fetch_js(template, args.url, args.max_shots, viewport)
    gen = Path(args.out).resolve().parent / "_fetch_url_artifacts.run.js"
    gen.parent.mkdir(parents=True, exist_ok=True)
    gen.write_text(js, encoding="utf-8")
    proc = flow.run(args, flow.cmd(args, "run-code", "--filename", str(gen), "--raw"), capture=True)
    if proc.stderr:
        log(proc.stderr.strip()[:500])
    result = parse_runcode_json(proc.stdout)
    if not result.get("ok"):
        raise SystemExit(f"url fetch failed: {result.get('note') or result}")
    gen.unlink(missing_ok=True)
    return result


def distill_facts(codex_cmd: str, facts: dict) -> dict:
    """Run codex with DISTILL_SCHEMA to turn raw extraction into marketing facts."""
    prompt = build_distill_prompt(facts)
    base = shlex.split(codex_cmd)
    with tempfile.TemporaryDirectory(prefix="ingest_url_") as tmp:
        schema_path = Path(tmp) / "schema.json"
        answer_path = Path(tmp) / "answer.json"
        schema_path.write_text(json.dumps(DISTILL_SCHEMA, ensure_ascii=False), encoding="utf-8")
        cmd = base + [
            "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--color",
            "never", "--output-schema", str(schema_path), "-o", str(answer_path),
        ]
        log("+ " + shlex.join(cmd))
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True)
        if proc.stderr:
            log(proc.stderr)
        text = ""
        if answer_path.exists():
            text = answer_path.read_text(encoding="utf-8").strip()
        if not text:
            text = (proc.stdout or "").strip()
        if not text:
            raise SystemExit("codex produced no page-facts output")
    return _extract_json(text)


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise SystemExit("no JSON object found in codex output")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in codex output: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("codex output was not a JSON object")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest a URL into grounded page facts (url-ad Stage 0).")
    p.add_argument("--url", required=True, help="website/product page URL to ingest")
    p.add_argument("--out", default="page_facts.json", help="output page_facts JSON path")
    p.add_argument(
        "--target-format", choices=["vertical", "horizontal"], default="vertical",
        help="target video format (drives the screenshot viewport)",
    )
    p.add_argument("--max-shots", type=int, default=4, help="max viewport screenshots to capture")
    p.add_argument("--codex", default="codex", help="codex CLI command for fact distillation")
    # Browser session flags (shared with google_flow_cli's attach/cmd/run helpers).
    p.add_argument("--cli", default="npx @playwright/cli@latest")
    p.add_argument("--npm-cache", default="")
    p.add_argument("--session", default="urlad")
    p.add_argument(
        "--capture-mode", choices=["launch", "attach"], default="launch",
        help="launch a fresh agent browser (public URLs, no login) or attach to "
             "the user's logged-in Chrome (authenticated pages)",
    )
    p.add_argument("--reuse-session", action="store_true", help="skip bootstrap; reuse an open session")
    p.add_argument("--attach", choices=["cdp", "extension"], default="cdp", help="attach target (capture-mode=attach)")
    p.add_argument("--cdp-endpoint", default="chrome")
    p.add_argument("--extension-channel", default="chrome")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    result = fetch_artifacts(args)
    _close_browser(args)
    screenshots = write_screenshots(result.get("shots") or [], out.parent / "page_facts_shots")
    distilled = distill_facts(args.codex, result.get("facts") or {})
    page_facts = assemble_page_facts(distilled, result.get("facts") or {}, args.url, screenshots)
    out.write_text(json.dumps(page_facts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out), "shots": len(screenshots)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
