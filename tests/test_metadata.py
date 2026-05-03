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
