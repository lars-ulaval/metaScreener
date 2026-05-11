# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_metadata.py - Repo metadata consistency regression tests.

These tests catch silent drift between version-related metadata files
(pyproject.toml, CITATION.cff, CHANGELOG.md) and between README badges
and the actual CI surface. They are deliberately lightweight (no
imports of the application, no fixtures) so they run as a pure-text
regression layer over repo-root files.
"""
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


class TestMetadataConsistency:
    def test_pyproject_citation_changelog_version_match(self):
        """pyproject.toml, CITATION.cff, and CHANGELOG.md's most-recent
        Released entry must agree on the current version. The
        [Unreleased] block does NOT count - that's the holding pen
        for the next release.

        NOTE: At Conv 7 start, pyproject/CITATION are at 3.1.0
        (preparing for the v3.1.0 release in Conv 10) but CHANGELOG's
        most-recent Released entry is still [3.0.1]. This test is
        marked xfail until Conv 10 cuts the v3.1.0 tag and creates
        the matching CHANGELOG entry. The xfail documents the
        pending-release state without breaking the suite; when
        Conv 10 lands, removing the xfail() call activates the
        equality assertions below.
        """
        pyproject = _read("pyproject.toml")
        citation = _read("CITATION.cff")
        changelog = _read("CHANGELOG.md")

        m_pyp = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
        m_cff = re.search(r'^version:\s*"?([^"\s]+)"?', citation, re.M)
        # First [N.N.N] - YYYY-MM-DD entry (under [Unreleased]) is the
        # most-recent Released version.
        m_chl = re.search(r'^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}',
                          changelog, re.M)

        assert m_pyp, "pyproject.toml has no version field"
        assert m_cff, "CITATION.cff has no version field"
        assert m_chl, "CHANGELOG.md has no released version entry"

        pytest.xfail(
            "Pending Conv 10 release: pyproject/CITATION at 3.1.0 but "
            "CHANGELOG most-recent-Released still 3.0.1. Test will pass "
            "once the v3.1.0 tag is cut and CHANGELOG entry created."
        )

        # When Conv 10 removes the xfail above, these assertions
        # become active and enforce three-way version agreement.
        assert m_pyp.group(1) == m_cff.group(1) == m_chl.group(1), (
            f"Version drift: pyproject={m_pyp.group(1)!r}, "
            f"CITATION={m_cff.group(1)!r}, CHANGELOG={m_chl.group(1)!r}"
        )

    def test_readme_tested_on_badge_lists_actual_ci_platforms(self):
        """The README.md must either expose a live GitHub Actions CI
        badge (preferred, after Conv 7 Commit 1) or a static "Tested on"
        badge that mentions both Ubuntu and Windows. Catches a regression
        where someone removes the live badge without restoring the
        static one (or vice-versa).
        """
        readme = _read("README.md")
        has_actions_badge = "actions/workflows/test.yml" in readme
        has_static_badge = (
            "Tested on" in readme
            and "Ubuntu" in readme
            and "Windows" in readme
        )
        assert has_actions_badge or has_static_badge, (
            "README.md must either show a GitHub Actions CI badge "
            "(actions/workflows/test.yml) or a static 'Tested on' "
            "badge listing Ubuntu and Windows."
        )


# Pattern for a non-image markdown link [text](url-or-path). The
# negative lookbehind excludes image links (which start with `![`).
# The captured group is the URL or relative path.
_MARKDOWN_LINK_RE = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)]+)\)")


def _markdown_files_in_repo():
    """Return all tracked-by-convention Markdown files: README.md plus
    everything under docs/ (recursively). Sample docs under docs_/ are
    out of scope: they are intentionally minimal and may carry
    placeholder references.
    """
    out = [PROJECT_ROOT / "README.md"]
    docs_dir = PROJECT_ROOT / "docs"
    if docs_dir.is_dir():
        out.extend(sorted(docs_dir.rglob("*.md")))
    return out


def _split_link_target(target):
    """Split a markdown link target on the '#' anchor separator.

    Returns (path_part, anchor_part). Either may be empty:
      "foo.md"        -> ("foo.md", "")
      "foo.md#bar"    -> ("foo.md", "bar")
      "#bar"          -> ("", "bar")
    """
    if "#" in target:
        path, _, anchor = target.partition("#")
        return path, anchor
    return target, ""


class TestDocsCrossReferences:
    """Cross-reference integrity for the documentation surface.

    Catches the most common broken-link regressions when docs are
    moved, renamed, or referenced before they exist. Operates as
    pure-text linting against repo-root files; no application
    imports.
    """

    def test_internal_markdown_links_resolve(self):
        """Every relative link inside README.md and docs/*.md must
        point to an existing file (or be an external http(s) URL,
        a mailto: URL, or an in-page anchor). Catches typos and
        forward-references to files that have not been created yet.
        """
        problems = []
        for md_path in _markdown_files_in_repo():
            try:
                text = md_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for match in _MARKDOWN_LINK_RE.finditer(text):
                raw_target = match.group(1).strip()
                # External or scheme-prefixed URLs: skip.
                if raw_target.startswith(("http://", "https://", "mailto:")):
                    continue
                # Pure in-page anchors: skip (a referenced heading
                # would require parsing the same file's headings; out
                # of scope for this test).
                if raw_target.startswith("#"):
                    continue
                path_part, _anchor = _split_link_target(raw_target)
                if not path_part:
                    continue
                # Resolve relative to the .md file's directory.
                referenced = (md_path.parent / path_part).resolve()
                if not referenced.exists():
                    problems.append(
                        f"{md_path.relative_to(PROJECT_ROOT)} -> "
                        f"{raw_target} (resolves to {referenced})"
                    )
        assert not problems, (
            "Broken internal markdown links:\n  "
            + "\n  ".join(problems)
        )

    def test_every_doc_listed_in_index(self):
        """Every .md file under docs/ (except docs/index.md itself)
        must be referenced by docs/index.md. This keeps the
        documentation hub honest as new docs are added.
        """
        docs_dir = PROJECT_ROOT / "docs"
        if not docs_dir.is_dir():
            pytest.skip("docs/ directory not present")
        index_path = docs_dir / "index.md"
        assert index_path.exists(), "docs/index.md must exist"
        index_text = index_path.read_text(encoding="utf-8")

        missing = []
        for md_path in sorted(docs_dir.rglob("*.md")):
            if md_path.name == "index.md":
                continue
            # Reference can use either bare filename or relative path
            # from docs/index.md; we accept either.
            rel = md_path.relative_to(docs_dir).as_posix()
            bare = md_path.name
            if rel not in index_text and bare not in index_text:
                missing.append(rel)

        assert not missing, (
            "Docs not referenced from docs/index.md:\n  "
            + "\n  ".join(missing)
        )

    def test_readme_links_to_docs_index(self):
        """The README must surface the documentation hub. After C4,
        README.md contains a Documentation section that links to
        docs/index.md; this test catches a regression where the
        section is removed or the link rotted.
        """
        readme = _read("README.md")
        assert "docs/index.md" in readme, (
            "README.md must contain a link to docs/index.md "
            "(the documentation hub). Was the Documentation section "
            "removed or the link path changed?"
        )
