# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_wave12_measurement_freeze.py — F-159: the evidence behind
``docs/llm-evaluation.md`` § *Local models on this corpus: a direct
measurement* is committed, and the document's figures are re-derived from it
on every suite run.

Why this file exists
--------------------
The measurement published in wave 12 session B derived from three bundle zips
in ``_archive_bundles/`` — a sibling directory of the repository, not under
version control. Every figure in that section therefore traced to files on one
machine, and nothing in the repository said where they were. That is F-98's
defect displaced onto a different artefact: *a published document depending on
evidence nothing protects*. The machine restarting mid-session is the argument
for why "they are on the disk" is not an answer.

What is frozen, and what is deliberately not
--------------------------------------------
The three bundles are 4.16 MB; ``docs/data/wave12_local_runs/`` is 0.78 MB.
The difference is not evidence. Four of the bundle members are byte-identical
across all three runs (the deterministic EH/IH reports — that identity *is*
the document's "the deterministic stages reproduce exactly" claim, and a
digest proves it as well as a copy would), one is byte-identical to
``samples/20260122_1654_aggregate.csv``, and one — ``IH_SURVIVORS.csv``, the
85-record EL input — is byte-identical to the *already frozen*
``docs/data/study_input/el_input_v3.1.0.csv``. Those equalities are asserted
here rather than assumed, which is what makes the omission safe.

What guards the freeze, and why none of it is a hand-maintained list
--------------------------------------------------------------------
Same rule ``test_study_input_freeze.py`` follows, for the same reason — this
project has been bitten repeatedly by lists that fall silently out of sync
with the thing they enumerate. So:

1. *Coverage* — the frozen set is read off the directory and the digest set
   off ``SHA256SUMS``, and the two must agree **in both directions**.
2. *Self-authentication* — every committed artefact is matched against the
   digest recorded for it inside its **own run's manifest**, which is itself
   one of the committed artefacts. The mapping from committed filename to
   manifest key is derived by basename, not listed. This is the property that
   makes the reduction honest: the manifests also carry digests for the
   members that were *not* committed, so a bundle that resurfaces can be
   matched member by member.
3. *Anchoring* — the omitted members' digests, read out of the manifests, are
   compared against the files already in the repository that carry the same
   bytes.
4. *Fidelity* — the strongest guard, and the reason a digest alone is not
   enough. Every headline figure in the published section is **recomputed from
   the frozen artefacts** and the document is then required to state it. The
   artefacts are the source of truth; the prose has to agree with them. Edit a
   number in the document and this fails; let the artefacts drift and (2)
   fails first.
5. *Bytes* — ``.gitattributes`` must keep these files out of ``* text=auto``.
   The ``EL_FULL.csv`` files are the sharp case: CRLF row terminators with
   bare LFs inside quoted abstracts is exactly the mixed content that gets
   normalised, and a fresh clone would break every digest at once.
"""
import csv
import functools
import hashlib
import io
import json
import re
import statistics
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT

FROZEN_DIR = PROJECT_ROOT / "docs" / "data" / "wave12_local_runs"
SUMS_PATH = FROZEN_DIR / "SHA256SUMS"
STUDY_INPUT = PROJECT_ROOT / "docs" / "data" / "study_input"
EVAL_DOC = PROJECT_ROOT / "docs" / "llm-evaluation.md"
SAMPLES = PROJECT_ROOT / "samples"

# Sidecars describe the freeze; they are not part of what is frozen.
_SIDECARS = {"SHA256SUMS", "wave12_local_runs.meta.txt"}

# The three runs, keyed by the filename prefix each one's artefacts carry.
# Derived from the directory below rather than trusted — see
# ``test_the_run_prefixes_are_the_ones_on_disk``.
_RUN_PREFIXES = ("runA_llama32", "runB_llama32", "runC_qwen25")


def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _sha256(path):
    return _sha256_bytes(Path(path).read_bytes())


def _frozen_files():
    """Every frozen artefact, derived from the directory itself."""
    return sorted(
        p for p in FROZEN_DIR.iterdir()
        if p.is_file() and p.name not in _SIDECARS
    )


def _recorded_digests():
    """Parse ``SHA256SUMS`` (digest, two spaces, name) into ``{name: digest}``."""
    out = {}
    for line in SUMS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        out[name.strip()] = digest.strip().lower()
    return out


@functools.lru_cache(maxsize=None)
def _manifest(prefix):
    return json.loads(
        (FROZEN_DIR / ("%s_manifest.json" % prefix)).read_text(encoding="utf-8-sig")
    )


def _el_history(prefix):
    hist = _manifest(prefix)["pipeline"]["history"]
    el = [h for h in hist if h.get("stage") == "EL"]
    assert len(el) == 1, "%s: expected exactly one EL history entry" % prefix
    return el[0]


@functools.lru_cache(maxsize=None)
def _el_full(prefix):
    """The run's 85 EL records, as a list of dicts."""
    text = (FROZEN_DIR / ("%s_EL_FULL.csv" % prefix)).read_text(encoding="utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


@functools.lru_cache(maxsize=None)
def _judgments(prefix):
    """``{(record_id, criterion): evidence_dict}`` for the run."""
    out = {}
    for row in _el_full(prefix):
        blob = row.get("el_evidence_json") or ""
        for crit, ev in (json.loads(blob) if blob else {}).items():
            out[(row["local_id"], crit)] = ev
    return out


@functools.lru_cache(maxsize=None)
def _cache_entries(prefix):
    """The raw per-judgment model answers from the run's cache."""
    lines = (FROZEN_DIR / ("%s_EL_cache.jsonl" % prefix)).read_text(
        encoding="utf-8"
    ).splitlines()
    return [json.loads(l)["val"] for l in lines if l.strip()]


def _excluded(prefix):
    return {r["local_id"] for r in _el_full(prefix) if r["el_outcome"] == "OUT"}


@functools.lru_cache(maxsize=None)
def _baseline():
    """The audited ``gpt-4o-mini`` baseline, already frozen under F-98."""
    text = (STUDY_INPUT / "el_filtered_v3.1.0.csv").read_text(encoding="utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


@functools.lru_cache(maxsize=None)
def _doc_text():
    return EVAL_DOC.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=None)
def _doc_lines():
    """Document lines with markdown emphasis stripped and runs of whitespace
    collapsed, so a figure can be located without pinning its formatting."""
    out = []
    for line in _doc_text().splitlines():
        flat = line.replace("*", "").replace("`", "")
        out.append(re.sub(r"\s+", " ", flat).strip())
    return out


def _doc_row(prefix_text):
    """The single normalised document line starting with ``prefix_text``."""
    hits = [l for l in _doc_lines() if l.startswith(prefix_text)]
    assert len(hits) == 1, (
        "Expected exactly one line in docs/llm-evaluation.md starting %r, "
        "found %d. The published tables this test reads have moved or been "
        "reformatted; re-point the test at them rather than deleting it."
        % (prefix_text, len(hits))
    )
    return hits[0]


def _cells(row):
    return [c.strip() for c in row.strip("| ").split("|")]


# ---------------------------------------------------------------------------


class TestTheFreezeIsCoveredWithoutAList:
    """Coverage, derived in both directions."""

    def test_the_frozen_directory_exists_and_is_not_empty(self):
        assert FROZEN_DIR.is_dir(), (
            "%s is missing — docs/llm-evaluation.md § 'Local models on this "
            "corpus' is citing evidence that is not in the repository." % FROZEN_DIR
        )
        assert _frozen_files()

    def test_every_frozen_file_has_a_recorded_digest(self):
        on_disk = {p.name for p in _frozen_files()}
        recorded = set(_recorded_digests())
        assert on_disk <= recorded, (
            "Frozen files with no digest in SHA256SUMS: %s. A file added to "
            "the freeze without a digest is unprotected."
            % sorted(on_disk - recorded)
        )

    def test_every_recorded_digest_names_a_frozen_file(self):
        on_disk = {p.name for p in _frozen_files()}
        recorded = set(_recorded_digests())
        assert recorded <= on_disk, (
            "SHA256SUMS names files that are not present: %s."
            % sorted(recorded - on_disk)
        )

    def test_the_frozen_bytes_are_unchanged(self):
        drifted = [
            "%s: recorded %s…, found %s…"
            % (name, digest[:12], _sha256(FROZEN_DIR / name)[:12])
            for name, digest in sorted(_recorded_digests().items())
            if (FROZEN_DIR / name).exists()
            and _sha256(FROZEN_DIR / name) != digest
        ]
        assert not drifted, (
            "The published measurement's evidence has changed:\n  "
            + "\n  ".join(drifted)
            + "\n\nThis is a citable dataset, not a fixture. It must not be "
              "re-captured or regenerated."
        )

    def test_the_run_prefixes_are_the_ones_on_disk(self):
        """The prefix tuple this module uses must match the directory, so a
        run added or renamed cannot be silently skipped by every test below."""
        found = sorted(
            p.name[: -len("_manifest.json")]
            for p in _frozen_files() if p.name.endswith("_manifest.json")
        )
        assert found == sorted(_RUN_PREFIXES), (
            "Manifests on disk are %s but this module iterates %s. Every "
            "assertion below would silently skip the difference."
            % (found, sorted(_RUN_PREFIXES))
        )


class TestTheArtefactsAuthenticateThemselves:
    """Self-authentication: each artefact against its own run's manifest."""

    @pytest.mark.parametrize("prefix", _RUN_PREFIXES)
    def test_each_artefact_matches_the_digest_in_its_own_manifest(self, prefix):
        recorded = _manifest(prefix)["sha256"]
        checked = 0
        for path in _frozen_files():
            if not path.name.startswith(prefix + "_"):
                continue
            basename = path.name[len(prefix) + 1:]
            # Derived by basename, not listed. A manifest does not hash itself.
            keys = [k for k in recorded if k.rsplit("/", 1)[-1] == basename]
            if not keys:
                continue
            assert len(keys) == 1, "%s: ambiguous manifest key for %s" % (
                prefix, basename)
            assert _sha256(path) == recorded[keys[0]], (
                "%s does not match the digest recorded for %s inside "
                "%s_manifest.json. The artefact and the manifest that "
                "describes it disagree, which means one of them was edited."
                % (path.name, keys[0], prefix)
            )
            checked += 1
        assert checked >= 2, (
            "%s: only %d artefact(s) were matched against the manifest — "
            "expected at least the EL_FULL.csv and EL_cache.jsonl."
            % (prefix, checked)
        )

    @pytest.mark.parametrize("prefix", _RUN_PREFIXES)
    def test_the_provenance_block_is_complete(self, prefix):
        prov = _el_history(prefix).get("provenance") or {}
        missing = {
            "model", "endpoint", "temperature", "prompt_version",
            "trunc_chars", "batch_size",
        } - set(prov)
        assert not missing, (
            "%s_manifest.json's EL provenance block is missing %s. The "
            "published section attributes every run from this block."
            % (prefix, sorted(missing))
        )

    @pytest.mark.parametrize("prefix", _RUN_PREFIXES)
    def test_the_manifest_counts_agree_with_the_records(self, prefix):
        counts = _el_history(prefix)["counts"]
        from collections import Counter
        actual = Counter(r["el_outcome"] for r in _el_full(prefix))
        for outcome, n in counts.items():
            assert actual.get(outcome, 0) == n, (
                "%s: manifest says %s=%d, EL_FULL.csv has %d."
                % (prefix, outcome, n, actual.get(outcome, 0))
            )
        assert sum(counts.values()) == len(_el_full(prefix)) == 85


class TestTheOmittedBundleMembersAreAccountedFor:
    """Anchoring — the reduction is safe only because these hold."""

    @pytest.mark.parametrize("prefix", _RUN_PREFIXES)
    def test_the_el_input_is_the_already_frozen_study_input(self, prefix):
        recorded = _manifest(prefix)["sha256"]["reports/IH_SURVIVORS.csv"]
        assert recorded == _sha256(STUDY_INPUT / "el_input_v3.1.0.csv"), (
            "%s ran the EL stage over an input that is NOT "
            "docs/data/study_input/el_input_v3.1.0.csv. The published section "
            "compares these runs with the audited baseline on the assumption "
            "that they screened the same 85 records." % prefix
        )

    def test_the_deterministic_reports_are_identical_across_the_three_runs(self):
        """The document's 'the deterministic stages reproduce exactly' claim,
        asserted by digest instead of by committing 3.8 MB three times."""
        shared = [
            "reports/EH_FULL.csv", "reports/EH_SURVIVORS.csv",
            "reports/IH_FULL.csv", "reports/IH_SURVIVORS.csv",
        ]
        for member in shared:
            digests = {_manifest(p)["sha256"][member] for p in _RUN_PREFIXES}
            assert len(digests) == 1, (
                "%s differs between the three runs: %s. The published section "
                "claims the deterministic funnel reproduced record for record."
                % (member, sorted(digests))
            )

    def test_the_corpus_member_is_the_committed_sample(self):
        aggregate = _sha256(SAMPLES / "20260122_1654_aggregate.csv")
        present = [
            p for p in _RUN_PREFIXES
            if "data/original.csv" in _manifest(p)["sha256"]
        ]
        assert present, "No run records data/original.csv."
        for prefix in present:
            assert _manifest(prefix)["sha256"]["data/original.csv"] == aggregate, (
                "%s's bundled corpus is not samples/20260122_1654_aggregate.csv, "
                "so omitting it from the freeze loses evidence." % prefix
            )

    def test_the_funnel_the_document_publishes_is_in_the_manifests(self):
        for prefix in _RUN_PREFIXES:
            hist = {h["stage"]: h for h in _manifest(prefix)["pipeline"]["history"]}
            assert hist["EH"]["counts"]["TOTAL_INTEGRAL"] == 776
            assert hist["EH"]["counts"]["OUT"] == 125
            assert hist["EH"]["survivors_rows"] == 651
            assert hist["IH"]["counts"]["OUT"] == 566
            assert hist["IH"]["survivors_rows"] == 85


class TestTheCriteriaTheELStageRead:
    """The A-vs-B comparison is sound only if the EL criteria were identical.

    They were — but the *table* was not, and that difference is recorded here
    so it cannot quietly disappear. It is a concrete instance of F-155's point
    about the provenance block: six fields are recorded, the criteria table is
    not one of them, and something did differ between runs A and B that no
    artefact of either run would have told you.
    """

    def _el_rows(self, path):
        text = Path(path).read_text(encoding="utf-8-sig")
        return {
            r["id"]: r for r in csv.DictReader(io.StringIO(text))
            if r["stage"] == "EL"
        }

    def test_run_a_used_the_already_frozen_criteria_table(self):
        assert _manifest("runA_llama32")["sha256"][
            "criteria/criteria_harmonized.csv"
        ] == _sha256(STUDY_INPUT / "criteria_harmonized_v3.1.0.csv"), (
            "Run A's criteria table is no longer byte-identical to the frozen "
            "study criteria, so omitting it from this directory loses evidence."
        )

    @pytest.mark.parametrize("prefix", ("runB_llama32", "runC_qwen25"))
    def test_runs_b_and_c_used_the_committed_variant(self, prefix):
        assert _manifest(prefix)["sha256"][
            "criteria/criteria_harmonized.csv"
        ] == _sha256(FROZEN_DIR / "runBC_criteria_harmonized.csv")

    def test_the_el_criteria_are_identical_despite_the_table_differing(self):
        a = self._el_rows(STUDY_INPUT / "criteria_harmonized_v3.1.0.csv")
        bc = self._el_rows(FROZEN_DIR / "runBC_criteria_harmonized.csv")
        assert set(a) == set(bc) == {"EC-2", "EC-3"}
        for cid in ("EC-2", "EC-3"):
            assert a[cid] == bc[cid], (
                "%s differs between run A's criteria table and runs B/C's. "
                "The published A-vs-B comparison rests on the EL stage having "
                "read the same criteria in both runs; it did not." % cid
            )

    def test_the_tables_do_differ_outside_the_el_stage(self):
        """Guards the *record* of the discrepancy. If this ever passes
        trivially the meta file's prominent warning has become false."""
        a = Path(STUDY_INPUT / "criteria_harmonized_v3.1.0.csv").read_bytes()
        bc = Path(FROZEN_DIR / "runBC_criteria_harmonized.csv").read_bytes()
        assert a != bc, (
            "Run A's and runs B/C's criteria tables are now identical. "
            "wave12_local_runs.meta.txt documents them as differing in IC-5; "
            "one of the two is wrong."
        )


class TestTheDocumentAgreesWithTheArtefacts:
    """Fidelity — every published figure, recomputed from the frozen bytes.

    A digest proves the evidence did not move. This proves the *prose* still
    says what the evidence says, which is the claim a reader actually relies
    on.
    """

    _RUN_LABELS = {
        "runA_llama32": "run A",
        "runB_llama32": "run B",
        "runC_qwen25": "run C",
    }

    @pytest.mark.parametrize("prefix", _RUN_PREFIXES)
    def test_the_results_table_states_the_exclusion_count(self, prefix):
        row = _doc_row("| %s |" % self._RUN_LABELS[prefix])
        n = len(_excluded(prefix))
        assert str(n) in _cells(row), (
            "The results table's %s row does not state %d exclusions, which "
            "is what %s_EL_FULL.csv contains.\n  row: %s"
            % (self._RUN_LABELS[prefix], n, prefix, row)
        )

    def test_the_document_names_the_records_that_moved_between_a_and_b(self):
        moved = sorted(_excluded("runB_llama32") - _excluded("runA_llama32"))
        assert moved, "Run B excluded nothing run A kept."
        assert ", ".join(moved) in _doc_text(), (
            "The document does not name %s as the records run B excluded and "
            "run A did not." % ", ".join(moved)
        )

    def test_the_document_names_the_qwen_exclusions(self):
        out = sorted(_excluded("runC_qwen25"))
        for rid in out:
            assert rid in _doc_text(), (
                "%s is excluded in runC_qwen25_EL_FULL.csv but is not named in "
                "the document, which discusses these individually." % rid
            )

    @pytest.mark.parametrize("prefix", _RUN_PREFIXES)
    def test_the_baseline_overlap_is_what_the_document_reports(self, prefix):
        kept = {r["local_id"] for r in _baseline() if r.get("el_outcome") != "OUT"}
        n = len(_excluded(prefix) & kept)
        assert str(n) in _doc_text(), (
            "The document does not state that %d of %s's exclusions were kept "
            "by the audited baseline." % (n, self._RUN_LABELS[prefix])
        )

    def test_the_single_correct_exclusion_is_named(self):
        base_out = {r["local_id"] for r in _baseline() if r.get("el_outcome") == "OUT"}
        assert len(base_out) == 1
        rid = base_out.pop()
        assert rid in _doc_text(), (
            "The baseline's one exclusion (%s) is not named in the document, "
            "which calls it the single overlap with the local runs." % rid
        )

    @pytest.mark.parametrize("prefix", _RUN_PREFIXES)
    def test_the_distribution_row_matches_the_evidence(self, prefix):
        from collections import Counter
        dec = Counter(e.get("decision") for e in _judgments(prefix).values())
        valid = sum(1 for v in _cache_entries(prefix) if v.get("valid_quote"))
        # The distribution table labels its rows with the model as well, which
        # is what distinguishes them from the results table's rows. Read the
        # model out of the manifest rather than spelling it here.
        model = _el_history(prefix)["provenance"]["model"]
        row = _doc_row("| %s %s " % (self._RUN_LABELS[prefix], model))
        cells = _cells(row)
        for key in ("meet", "not_meet", "uncertain"):
            assert str(dec.get(key, 0)) in cells, (
                "The distribution table's %s row does not state %s=%d.\n  row: %s"
                % (self._RUN_LABELS[prefix], key, dec.get(key, 0), row)
            )
        assert "%d/170" % valid in row, (
            "The distribution table's %s row does not state %d/170 valid "
            "quotes, which is what %s_EL_cache.jsonl contains.\n  row: %s"
            % (self._RUN_LABELS[prefix], valid, prefix, row)
        )

    def test_the_changed_decision_figure_is_what_the_evidence_shows(self):
        a, b = _judgments("runA_llama32"), _judgments("runB_llama32")
        keys = set(a) | set(b)
        changed = [k for k in keys if a.get(k, {}).get("decision")
                   != b.get(k, {}).get("decision")]
        assert "%d of %d" % (len(changed), len(keys)) in _doc_text(), (
            "The document does not state '%d of %d' changed decisions."
            % (len(changed), len(keys))
        )
        pct = "%.1f%%" % (100.0 * len(changed) / len(keys))
        assert pct in _doc_text(), (
            "The document does not state %s for the changed-decision share." % pct
        )

    def test_the_wider_evidence_variation_is_published_too(self):
        """The decision field is not the only thing that varied between the
        two runs, and the document has to say so — one of the three records
        that moved from flagged to excluded did so with both its decisions
        unchanged."""
        a, b = _judgments("runA_llama32"), _judgments("runB_llama32")
        keys = set(a) | set(b)
        fields = ("decision", "confidence", "field", "quote", "status")
        differing = {
            k for k in keys
            if any(a.get(k, {}).get(f) != b.get(k, {}).get(f) for f in fields)
        }
        assert "%d of %d" % (len(differing), len(keys)) in _doc_text(), (
            "The document does not state that %d of %d judgments differ in at "
            "least one evidence field between runs A and B. Publishing only "
            "the %d that changed decision understates the run-to-run "
            "variation by a factor of %.1f."
            % (len(differing), len(keys),
               sum(1 for k in keys
                   if a.get(k, {}).get("decision") != b.get(k, {}).get("decision")),
               len(differing) / max(1, sum(
                   1 for k in keys
                   if a.get(k, {}).get("decision") != b.get(k, {}).get("decision"))))
        )
        pct = "%.1f%%" % (100.0 * len(differing) / len(keys))
        assert pct in _doc_text()

    def test_the_record_that_moved_without_a_decision_change_is_named(self):
        a, b = _judgments("runA_llama32"), _judgments("runB_llama32")
        moved = _excluded("runB_llama32") - _excluded("runA_llama32")
        unexplained = sorted(
            rid for rid in moved
            if all(a.get((rid, c), {}).get("decision")
                   == b.get((rid, c), {}).get("decision")
                   for c in ("EC-2", "EC-3"))
        )
        assert len(unexplained) == 1, (
            "Expected exactly one record to have moved from flagged to "
            "excluded with both decisions unchanged; found %s." % unexplained
        )
        assert unexplained[0] in _doc_text()

    def test_the_truncation_figures_are_recomputable(self):
        text = (STUDY_INPUT / "el_input_v3.1.0.csv").read_text(encoding="utf-8-sig")
        abstracts = [
            (r.get("abstract") or "") for r in csv.DictReader(io.StringIO(text))
        ]
        assert max(len(a) for a in abstracts) <= 4000, (
            "An abstract exceeds 4000 characters, so the document's claim that "
            "the baseline saw every abstract in full is false."
        )
        over = [a for a in abstracts if len(a) > 1500]
        assert "%d of %d" % (len(over), len(abstracts)) in _doc_text()
        median = statistics.median(sorted(len(a) - 1500 for a in over))
        assert str(int(median)) in _doc_text(), (
            "The document does not state a median truncation loss of %d "
            "characters." % int(median)
        )

    def test_the_document_points_at_this_directory(self):
        assert "docs/data/wave12_local_runs" in _doc_text(), (
            "The published section does not tell a reader where its evidence "
            "is. That was the whole defect (F-159): figures that trace only to "
            "files on one machine."
        )


class TestTheFrozenBytesSurviveCheckout:
    """Bytes — the F-128-shaped trap, one directory over."""

    def test_gitattributes_exempts_the_frozen_evidence(self):
        text = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert "docs/data/wave12_local_runs/" in text, (
            "The frozen evidence is not exempt from `* text=auto`. The "
            "EL_FULL.csv files carry CRLF row terminators with bare LFs inside "
            "quoted abstracts; without a rule here a fresh clone rewrites them "
            "and every digest in the directory breaks at once."
        )
