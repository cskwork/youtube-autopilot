#!/usr/bin/env python3
"""Stage 0 of the URL-AD workflow: ingest a website URL into grounded page facts.

SCAFFOLD (router + spec pass). This module pins the CLI surface and the
``page_facts.json`` contract the URL-AD workflow is built on, and that
``stage_gates.gate_page_facts`` verifies. The LIVE capture -- driving the
attached Chrome to navigate the URL, extract Open Graph/meta + readable text,
and screenshot the page, then asking codex to distill marketing facts -- is
implemented in the next build pass. See ``references/workflows/url-ad.md`` for
the full pipeline design and the planned fetch helper
(``scripts/js/fetch_url_artifacts.tmpl.js``, built on the same attached-browser
``run-code`` pattern as ``google_flow_cli.py``).

Contract once implemented (one JSON line on stdout, logs on stderr):
  {"ok": true, "out": "<page_facts.json path>", "shots": <int>}
"""
from __future__ import annotations

import argparse
import sys

# The page_facts.json schema the script stage is grounded in. ``value_props``
# feed the USP slot of the hook -> USP -> CTA structure; ``cta_text`` feeds the
# CTA slot; ``screenshots`` become faithful Ken-Burns B-roll. ``gate_page_facts``
# verifies the required (url, title, value_props>=1, cta_text) subset.
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest a URL into grounded page facts (URL-AD Stage 0)."
    )
    parser.add_argument("--url", required=True, help="website/product page URL to ingest")
    parser.add_argument("--out", default="page_facts.json", help="output page_facts JSON path")
    parser.add_argument(
        "--target-format", choices=["vertical", "horizontal"], default="vertical",
        help="target video format (drives the screenshot viewport)",
    )
    parser.add_argument("--max-shots", type=int, default=4, help="max page screenshots to capture")
    parser.add_argument("--session", default="vya", help="Playwright agent session name")
    parser.add_argument("--no-attach", action="store_true", help="reuse an already-attached session")
    parser.add_argument("--codex", default="codex", help="codex CLI command for fact distillation")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Honest scaffold: the live browser capture is not implemented in this pass.
    # Emit a clear, non-zero failure rather than faking a successful artifact.
    print(
        f"ingest_url is scaffolded; live capture of {args.url!r} is pending the "
        "next build pass. See references/workflows/url-ad.md.",
        file=sys.stderr,
    )
    print('{"ok": false, "error": "ingest_url not yet implemented (scaffold)"}')
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
