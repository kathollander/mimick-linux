#!/usr/bin/env python3
"""Check how Mimick would read a folder of PDFs, without listening to them.

    .venv/bin/python tools/check_reading.py Testing/
    .venv/bin/python tools/check_reading.py somewhere/paper.pdf --show 12

Prints, per document, what fraction of the text it will read and any sentences
that look like layout trouble. Use it to find documents worth fixing with
Ctrl+R -- or worth reporting as a bug.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mimick.document import Document                      # noqa: E402
from mimick.layout import ASIDE, FURNITURE, SKIPPED       # noqa: E402

# Shapes that suggest a sentence was stitched together from separate regions.
# Deliberately conservative: a checker that cries wolf gets ignored. Proper
# nouns like "GeoJournal" tripped an earlier camel-case rule, so it was dropped.
SUSPECT = [
    (re.compile(r"\b(?:Received|Accepted|Published|Citation|Copyright|Licensee)\b"),
     "journal boilerplate"),
    (re.compile(r"\b\d+\s+of\s+\d+\b"), "a page number"),
    (re.compile(r"https?://|doi\.org"), "a web address"),
    (re.compile(r"\w-\s+\w"), "a word split across lines"),
    (re.compile(r"\b[a-z]+@[a-z0-9.]+\b"), "an email address"),
]


def review(path: Path, show: int) -> dict:
    document = Document(path)
    try:
        words = len(document.words)
        readable = sum(1 for word in document.words if word.readable)
        kinds: dict[str, int] = {}
        for regions in document.regions.values():
            for region in regions:
                kinds[region.kind] = kinds.get(region.kind, 0) + 1

        flagged = []
        for sentence in document.sentences:
            for pattern, why in SUSPECT:
                if pattern.search(sentence.text):
                    flagged.append((sentence.page + 1, why, sentence.text))
                    break

        print(f"\n{path.name}")
        print(f"  {document.page_count} pages, {len(document.sentences)} sentences")
        share = readable / words if words else 0
        print(f"  reading {readable} of {words} words ({share:.0%})")
        print("  regions: " + ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items())))

        if share < 0.5:
            print("  !! reading less than half the words - check the reading order")
        if not document.sentences:
            print("  !! nothing to read: a scan needing OCR, or an unusual layout")

        if flagged:
            print(f"  {len(flagged)} sentence(s) look like layout trouble:")
            for page, why, text in flagged[:show]:
                print(f"    p{page} ({why}): {' '.join(text.split())[:96]}")
            if len(flagged) > show:
                print(f"    … and {len(flagged) - show} more")
        else:
            print("  no suspicious sentences")
        return {"flagged": len(flagged), "share": share, "sentences": len(document.sentences)}
    finally:
        document.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="a PDF, or a folder of them")
    parser.add_argument("--show", type=int, default=6,
                        help="how many suspicious sentences to print per document")
    args = parser.parse_args()

    if args.target.is_dir():
        paths = sorted(args.target.glob("*.pdf"))
    else:
        paths = [args.target]
    if not paths:
        print(f"no PDFs found in {args.target}")
        return 1

    worst = 0
    for path in paths:
        try:
            result = review(path, args.show)
        except Exception as exc:
            print(f"\n{path.name}\n  !! could not be read: {exc}")
            worst = 1
            continue
        if result["flagged"] or result["share"] < 0.5 or not result["sentences"]:
            worst = 1

    print(f"\n{len(paths)} document(s) checked")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
