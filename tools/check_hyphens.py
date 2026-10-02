#!/usr/bin/env python3
"""Check that a word broken across a line is put back together the right way.

    .venv/bin/python tools/check_hyphens.py

"creat- ing" must close up to "creating", and "non- status" must keep its
hyphen, because the voice says whatever comes out of this and Ctrl+C copies it.
The rule is in document.py's _mark_hyphenation and _join_words; the cases below
are real ones from the documents in Testing/, which is where the rule was got
wrong the first time.

Both apps read this code, so this check covers the browser version too.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mimick.document import Document                       # noqa: E402

# (document, first half, second half, what it must come out as). Every one of
# these was read off a real page. A document is its file name in Testing/, or a
# nickname for one of Kat's own that Testing/local-documents.json (not in the
# repository) turns into its file name; without it, those are skipped.
CASES: list[tuple[str, str, str, str]] = [
    # The typesetter's hyphen: it goes, or the voice says "creat ing".
    ("maths-paper", "can-", "not", "cannot"),
    ("maths-paper", "mathe-", "matics", "mathematics"),
    ("maths-paper", "dispropor-", "tionately", "disproportionately"),
    ("Big Ideas from Atleo and Boron 2022.pdf", "creat-", "ing", "creating"),
    ("Big Ideas from Atleo and Boron 2022.pdf", "colonial-", "ism.", "colonialism."),

    # The word's own hyphen, proved by the document writing it elsewhere.
    # Before 18 September every one of these lost its hyphen and was spoken as
    # one run-together word.
    ("policy-paper", "“non-", "status", "“non-status"),
    ("policy-paper", "second-", "generation", "second-generation"),
    ("policy-paper", "self-", "government", "self-government"),
    ("column-paper",
     "well-", "being.", "well-being."),
    ("column-paper",
     "post-", "secondary)", "post-secondary)"),
    ("Big Ideas from Atleo and Boron 2022.pdf",
     "settler-", "colonial", "settler-colonial"),

    # A hyphen after a figure is always the word's own.
    ("Big Ideas from Atleo and Boron 2022.pdf", "113-", "year", "113-year"),

    # A break before a capital is a real hyphen -- a name, not a broken word.
    ("maths-paper", "Piatek-", "Jimenez", "Piatek-Jimenez"),

    # The document writes the closed form far more often than the hyphenated
    # one, so the single hyphenated occurrence does not get to outvote it.
    ("column-paper",
     "In-", "digenous", "Indigenous"),
    ("column-paper",
     "Home-", "land:", "Homeland:"),
    ("column-paper",
     "Teil-", "let,", "Teillet,"),
]


def local_name(name: str) -> str:
    """The file name for a nickname in Testing/local-documents.json, or ``name``."""
    try:
        known = json.loads((Path(__file__).resolve().parent.parent / "Testing"
                            / "local-documents.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    return known.get(name, name)


def main() -> int:
    here = Path(__file__).resolve().parent.parent / "Testing"
    failures: list[str] = []
    checked = 0

    for name in sorted({case[0] for case in CASES}):
        path = here / local_name(name)
        if not path.exists():
            print(f"  --    {name} is not in Testing/, skipped")
            continue
        document = Document(path)
        print(f"\n{name[:60]}")
        for _doc, first_half, second_half, expected in (c for c in CASES if c[0] == name):
            where = [
                index for index, word in enumerate(document.words[:-1])
                if word.text == first_half and word.joins_next
                and document.words[index + 1].text == second_half
            ]
            if not where:
                failures.append(f"{name}: {first_half!r}+{second_half!r} is not in this document")
                print(f"  FAIL  {first_half!r} + {second_half!r} -- no such break")
                continue
            checked += 1
            got = document.selection_text(where[0], where[0] + 1)
            ok = got == expected
            print(f"  {'ok  ' if ok else 'FAIL'}  {first_half!r} + {second_half!r} -> {got!r}"
                  f"{'' if ok else f'   expected {expected!r}'}")
            if not ok:
                failures.append(f"{name}: {first_half!r}+{second_half!r} gave {got!r}, "
                                f"expected {expected!r}")
        document.close()

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for line in failures:
            print(f"  {line}")
        return 1
    print(f"All {checked} broken words are put back together correctly.")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    # os._exit, not SystemExit: MainWindow fetches the voice list on a QThread,
    # and with no network to answer it that request outlives the bounded wait in
    # closeEvent. Qt then aborts the process as it tears down and the shell sees
    # 134, whether every check passed or none did -- which had these checks
    # reading as failures at random. Everything is finished and printed by this
    # point, so skipping the long way out costs nothing.
    import os

    os._exit(code)
