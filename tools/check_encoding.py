# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""tools/check_encoding.py - Fail on UTF-8 BOMs and Latin-1 mojibake.

Guards against the corruption class that reached `main` in commit 365325c:
a UTF-8 file read as cp1252/Latin-1 and written back as UTF-8-with-BOM.
That round trip prepends EF BB BF and expands every non-ASCII character
into a multi-character sequence - em-dashes become "a-circumflex + euro +
quote", accented letters become two characters, box-drawing characters in
ASCII art become three.

Two checks, over every tracked text file:

  1. BOM      - the file starts with the UTF-8 byte-order mark EF BB BF.
  2. Mojibake - the file contains one of the mojibake lead characters
                (U+00C2, U+00C3, U+00E2, U+00F0) immediately followed by
                another non-ASCII character.

The mojibake rule is deliberately structural rather than a list of known
bad sequences: an earlier draft of this checker enumerated specific byte
patterns and missed 21 of the 46 corrupted lines in README.md, because the
corrupted ASCII-art tree and the corrupted warning glyphs used sequences
that were not on the list. The lead-char-plus-non-ASCII rule catches every
form of the round trip at once.

Legitimate text does not trip it: accented letters in French, German, or
Spanish prose are followed by ASCII letters, not by further non-ASCII
characters.

Usage:
    python tools/check_encoding.py            # scan tracked files
    python tools/check_encoding.py PATH ...   # scan specific paths

Exit code 0 if clean, 1 otherwise. Designed for CI (pure Python, runs
identically on Linux, macOS, and Windows runners) and as a local
pre-commit gate.
"""
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

BOM = b"\xef\xbb\xbf"

# A mojibake lead character followed by any other non-ASCII character.
# U+00C2 A-circumflex, U+00C3 A-tilde, U+00E2 a-circumflex, U+00F0 eth:
# these are what the UTF-8 lead bytes C2/C3/E2/F0 decode to under cp1252
# and Latin-1.
MOJIBAKE_LEADS = "ÂÃâð"
MOJIBAKE_RE = re.compile("[" + MOJIBAKE_LEADS + "][-￿]")

# Extensions treated as text. Anything else is skipped: binary payloads may
# legitimately contain these byte sequences.
TEXT_SUFFIXES = {
    ".md", ".py", ".txt", ".toml", ".cfg", ".ini", ".yml", ".yaml",
    ".json", ".cff", ".spec", ".sh", ".csv", ".jsonl", ".html", ".css",
}
# Extensionless or dot-prefixed files that are still text.
TEXT_NAMES = {"LICENSE", "Dockerfile", ".gitignore", ".gitattributes", ".env.example"}

# Paths exempt from the scan.
EXCLUDED_PREFIXES = (
    "tests/golden/",            # byte-identity fixtures, marked binary in .gitattributes
    "docs/data/",               # committed study evidence, reproduced byte-for-byte
    "docs/internal/",           # the diagnostic report quotes mojibake as evidence
    "tools/check_encoding.py",  # this file describes the patterns it looks for
)


def _is_text(rel):
    p = Path(rel)
    return p.suffix.lower() in TEXT_SUFFIXES or p.name in TEXT_NAMES


def _tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def _describe(match):
    """Render a mojibake match as codepoint names, for an actionable message."""
    return " + ".join(
        "U+%04X %s" % (ord(ch), unicodedata.name(ch, "?")) for ch in match
    )


def scan(paths):
    """Return a list of human-readable problem strings."""
    problems = []
    for rel in paths:
        norm = rel.replace("\\", "/")
        if norm.startswith(EXCLUDED_PREFIXES):
            continue
        if not _is_text(norm):
            continue
        path = Path(rel)
        if not path.is_file():
            continue
        data = path.read_bytes()

        if data.startswith(BOM):
            problems.append("%s:1: UTF-8 BOM (EF BB BF) at start of file" % norm)
            data = data[len(BOM):]

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            problems.append("%s: not valid UTF-8 (%s)" % (norm, exc))
            continue

        for lineno, line in enumerate(text.split("\n"), 1):
            seen = set()
            for m in MOJIBAKE_RE.finditer(line):
                if m.group(0) in seen:
                    continue
                seen.add(m.group(0))
                problems.append(
                    "%s:%d: mojibake %r - %s"
                    % (norm, lineno, m.group(0), _describe(m.group(0)))
                )
    return problems


def main(argv):
    paths = argv[1:] or _tracked_files()
    problems = scan(paths)
    if problems:
        print("Encoding check FAILED:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        print(
            "\n%d problem(s). Text files must be UTF-8 without a BOM.\n"
            "Mojibake means a file was read as cp1252/Latin-1 and re-written as\n"
            "UTF-8. Check your editor's encoding, and avoid PowerShell 5.1's\n"
            "Set-Content / Out-File defaults, which do exactly that." % len(problems),
            file=sys.stderr,
        )
        return 1
    print("Encoding check passed: %d path(s) scanned, no BOM or mojibake." % len(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
