# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""test_harmoniser_chunked_refine.py — F-185/F-186, wave 15d.

The invariant every class here serves: **Harmonise + LLM can never make
the table worse than the no-LLM parse.** Chunked calls at the measured-
safe size (four — three byte-identical successes in 08 §8a, argued from
the measurement so the F-107 unconstrained fallback sits inside the
evidence too), each chunk schema-constrained with cardinality = chunk
size, one re-ask for structural residue, then per-row fallback to the
deterministic row with a plain-language reason — never a worker abort,
never jargon, never a lost row.

The seven scripted failure modes of the never-worse property:
  1. a malformed (unparseable) chunk reply
  2. a VALID row for a FOREIGN id — present nowhere in the chunk; must
     be rejected to fallback, never absorbed (adjudication note 1)
  3. duplicated ids in one reply
  4. a validation reject (multi-sentence `what` on a semantic rule)
  5. total garbage (prose, no JSON anywhere)
  6. an empty rows list
  7. a reply omitting some of the chunk's rows

Doubles prove everything except real model behaviour; the live half is
the maintainer's exact failure re-run, budgeted and gated in the wave
report.
"""
import json
import threading  # noqa: F401  (parity with sibling files)

import pytest

from conftest import _import_plugin

import plugins._common.llm_client as lc


def _refine():
    return _import_plugin("03_harmoniser", "llm_refine")


def _hparser():
    return _import_plugin("03_harmoniser", "parser")


def _vreport():
    return _import_plugin("03_harmoniser", "validate_report")


COLS = ["title", "abstract", "keywords", "lang", "year", "venue"]


def _row(i, **kw):
    base = {"stage": "IL", "id": f"IC-{i}", "type": "include",
            "scope": "metadata", "label": f"Criterion {i} sentence.",
            "operator": "llm", "target": "keywords",
            "what": [f"Criterion {i} sentence."], "threshold": "0.60",
            "enabled": True, "source_text": f"IC-{i} - text"}
    base.update(kw)
    return base


def _reply_row(r, **kw):
    out = {"id": r["id"], "type": r["type"], "stage": r["stage"],
           "label": r["label"], "operator": r["operator"],
           "target": r["target"], "what": list(r["what"]),
           "threshold": r["threshold"], "enabled": True}
    out.update(kw)
    return out


class _ScriptedClient:
    """One reply (or exception) per create() call, in order; records
    every request's kwargs. The last script entry repeats if calls
    outnumber entries."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.requests = []
        outer = self

        class _Completions:
            def create(self, **kw):
                outer.requests.append(kw)
                idx = min(len(outer.requests) - 1, len(outer.scripts) - 1)
                item = outer.scripts[idx]
                if isinstance(item, Exception):
                    raise item
                msg = type("M", (), {"content": item})
                choice = type("C", (), {"message": msg,
                                        "finish_reason": "stop"})
                usage = type("U", (), {"prompt_tokens": 100,
                                       "completion_tokens": 50,
                                       "total_tokens": 150})
                return type("R", (), {"choices": [choice],
                                      "usage": usage})()

        self.chat = type("Chat", (), {"completions": _Completions()})()


def _rows_json(rows):
    return json.dumps({"rows": rows})


def _run(monkeypatch, in_rows, scripts, window=None):
    mod = _refine()
    client = _ScriptedClient(scripts)
    monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: client)
    if window is not None:
        monkeypatch.setattr(lc, "resolve_context_window",
                            lambda *_a, **_k: window)
    logs = []
    rows, outcome = mod._llm_refine(in_rows, "full text", COLS, model="m",
                                    log=logs.append)
    return rows, outcome, client, logs


def _good_scripts(in_rows, chunk):
    """Scripts answering every chunk correctly."""
    out = []
    for i in range(0, len(in_rows), chunk):
        out.append(_rows_json([_reply_row(r)
                               for r in in_rows[i:i + chunk]]))
    return out


# ---------------------------------------------------------------------------
# 1. the chunk arithmetic and the request shape
# ---------------------------------------------------------------------------

class TestChunking:
    def test_eight_go_as_four_plus_four(self, monkeypatch):
        in_rows = [_row(i) for i in range(8)]
        _rows, outcome, client, _l = _run(
            monkeypatch, in_rows, _good_scripts(in_rows, 4))
        assert len(client.requests) == 2
        sizes = [len(json.loads(r["messages"][1]["content"])["rows"])
                 for r in client.requests]
        assert sizes == [4, 4]
        assert sorted(outcome.refined) == sorted(r["id"] for r in in_rows)

    def test_six_go_as_four_plus_two(self, monkeypatch):
        in_rows = [_row(i) for i in range(6)]
        _rows, _o, client, _l = _run(
            monkeypatch, in_rows, _good_scripts(in_rows, 4))
        sizes = [len(json.loads(r["messages"][1]["content"])["rows"])
                 for r in client.requests]
        assert sizes == [4, 2]

    def test_three_go_as_one_call(self, monkeypatch):
        in_rows = [_row(i) for i in range(3)]
        _rows, _o, client, _l = _run(
            monkeypatch, in_rows, _good_scripts(in_rows, 4))
        assert len(client.requests) == 1

    def test_the_constant_is_the_measured_safe_size(self):
        assert _refine().HARMONISER_CHUNK_SIZE == 4

    def test_every_request_is_schema_constrained_with_chunk_cardinality(
            self, monkeypatch):
        in_rows = [_row(i) for i in range(6)]
        _rows, _o, client, _l = _run(
            monkeypatch, in_rows, _good_scripts(in_rows, 4))
        for req, n in zip(client.requests, (4, 2)):
            rf = req.get("response_format")
            assert rf and rf["type"] == "json_schema"
            assert rf["json_schema"]["strict"] is True
            arr = rf["json_schema"]["schema"]["properties"]["rows"]
            assert arr["minItems"] == arr["maxItems"] == n

    def test_the_enums_are_the_parser_vocabularies_not_a_copy(self):
        mod, hp = _refine(), _hparser()
        rf = mod._response_format_for_rows(4)
        props = rf["json_schema"]["schema"]["properties"]["rows"]["items"][
            "properties"]
        assert tuple(props["stage"]["enum"]) == tuple(hp.STAGES)
        assert tuple(props["operator"]["enum"]) == tuple(hp.OPERATORS)
        assert set(rf["json_schema"]["schema"]["properties"]["rows"]["items"]
                   ["required"]) >= {"id", "stage", "type", "label",
                                    "operator", "target", "what",
                                    "threshold", "enabled"}

    def test_max_tokens_is_a_cost_bound_scaled_to_the_chunk(
            self, monkeypatch):
        in_rows = [_row(i) for i in range(6)]
        _rows, _o, client, _l = _run(
            monkeypatch, in_rows, _good_scripts(in_rows, 4))
        mts = [r.get("max_tokens") for r in client.requests]
        assert all(isinstance(m, int) and m > 0 for m in mts)
        assert mts[0] > mts[1], "the bound scales with the chunk"


# ---------------------------------------------------------------------------
# 2. the never-worse property — seven scripted failure modes
# ---------------------------------------------------------------------------

def _assert_never_worse(in_rows, out_rows, outcome):
    assert [r["id"] for r in out_rows] == [r["id"] for r in in_rows], (
        "exactly the input criteria, in input order — no row lost, none "
        "invented")
    by_id = {r["id"]: r for r in in_rows}
    for r in out_rows:
        if r["id"] in outcome.kept:
            assert r == by_id[r["id"]], (
                "a kept row is the deterministic row, byte for byte")
    assert set(outcome.kept) | set(outcome.refined) \
        == {r["id"] for r in in_rows}
    assert not (set(outcome.kept) & set(outcome.refined))


class TestNeverWorse:
    """No scripted failure may lose a row, invent a row, or escape as an
    exception. Modes 1–7 of the wave design plus adjudication note 1."""

    def _two_chunks(self):
        return [_row(i) for i in range(8)]

    def test_1_malformed_chunk_reply(self, monkeypatch):
        in_rows = self._two_chunks()
        good = _rows_json([_reply_row(r) for r in in_rows[4:]])
        bad = '{"rows": [{"id": "IC-0", "type": '   # cut mid-object
        rows, outcome, _c, _l = _run(monkeypatch, in_rows,
                                     [bad, good, bad])
        _assert_never_worse(in_rows, rows, outcome)
        assert set(outcome.kept) == {f"IC-{i}" for i in range(4)}

    def test_2_a_valid_row_for_a_foreign_id_is_never_absorbed(
            self, monkeypatch):
        """Adjudication note 1: an id NOT in the chunk can and must be
        rejected to fallback, not absorbed."""
        in_rows = [_row(i) for i in range(4)]
        foreign = _reply_row(_row(99))
        reply = _rows_json([_reply_row(r) for r in in_rows[:3]] + [foreign])
        rows, outcome, _c, _l = _run(monkeypatch, in_rows,
                                     [reply, reply])
        _assert_never_worse(in_rows, rows, outcome)
        assert "IC-99" not in [r["id"] for r in rows]
        assert "IC-3" in outcome.kept

    def test_3_duplicated_ids_fall_back(self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        dup = _reply_row(in_rows[0], label="Second copy, different.")
        reply = _rows_json([_reply_row(r) for r in in_rows[:3]] + [dup])
        rows, outcome, _c, _l = _run(monkeypatch, in_rows, [reply, reply])
        _assert_never_worse(in_rows, rows, outcome)
        assert "IC-0" in outcome.kept, (
            "two proposals for one criterion is no proposal")
        assert "IC-3" in outcome.kept

    def test_4_a_validation_reject_keeps_the_original_with_a_reason(
            self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        bad = _reply_row(in_rows[0],
                         what=["One sentence.", "A second sentence."])
        reply = _rows_json([bad] + [_reply_row(r) for r in in_rows[1:]])
        rows, outcome, _c, _l = _run(monkeypatch, in_rows, [reply])
        _assert_never_worse(in_rows, rows, outcome)
        assert "IC-0" in outcome.kept
        assert "sentence" in outcome.kept["IC-0"]
        assert "llm" not in outcome.kept["IC-0"]

    def test_5_total_garbage(self, monkeypatch):
        in_rows = self._two_chunks()
        rows, outcome, _c, _l = _run(
            monkeypatch, in_rows,
            ["I cannot help with that request."] * 4)
        _assert_never_worse(in_rows, rows, outcome)
        assert set(outcome.kept) == {r["id"] for r in in_rows}
        assert outcome.refined == []

    def test_6_an_empty_rows_list(self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        rows, outcome, _c, _l = _run(monkeypatch, in_rows,
                                     [_rows_json([])] * 2)
        _assert_never_worse(in_rows, rows, outcome)
        assert set(outcome.kept) == {r["id"] for r in in_rows}

    def test_7_a_reply_omitting_rows(self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        partial = _rows_json([_reply_row(r) for r in in_rows[:2]])
        rest = _rows_json([_reply_row(r) for r in in_rows[2:]])
        rows, outcome, _c, _l = _run(monkeypatch, in_rows,
                                     [partial, rest])
        _assert_never_worse(in_rows, rows, outcome)
        assert set(outcome.refined) == {r["id"] for r in in_rows}, (
            "the residue re-ask recovered the omitted half")

    def test_a_transport_error_still_surfaces(self, monkeypatch):
        """Out of containment scope by design: a refused connection is
        not a refinement rejection, and its message is the actionable
        cause (F-146's fix). The table is untouched either way — the
        View assigns state.rows only on success (F-185's own cell)."""
        in_rows = [_row(i) for i in range(2)]
        with pytest.raises(Exception) as ei:
            _run(monkeypatch, in_rows,
                 [RuntimeError("Connection refused")])
        assert "Connection refused" in str(ei.value)


# ---------------------------------------------------------------------------
# 3. the re-ask
# ---------------------------------------------------------------------------

class TestTheReask:
    def test_residue_is_reasked_once_at_residue_cardinality(
            self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        partial = _rows_json([_reply_row(r) for r in in_rows[:3]])
        rest = _rows_json([_reply_row(in_rows[3])])
        _rows_out, outcome, client, _l = _run(monkeypatch, in_rows,
                                              [partial, rest])
        assert len(client.requests) == 2
        rf = client.requests[1]["response_format"]
        arr = rf["json_schema"]["schema"]["properties"]["rows"]
        assert arr["minItems"] == arr["maxItems"] == 1
        assert outcome.kept == {}

    def test_a_clean_chunk_is_not_reasked(self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        _rows_out, _o, client, _l = _run(
            monkeypatch, in_rows, _good_scripts(in_rows, 4))
        assert len(client.requests) == 1

    def test_the_reask_happens_at_most_once(self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        partial = _rows_json([_reply_row(r) for r in in_rows[:2]])
        _rows_out, outcome, client, _l = _run(
            monkeypatch, in_rows, [partial, partial, partial, partial])
        assert len(client.requests) == 2, "one chunk call + one re-ask"
        assert set(outcome.kept) == {"IC-2", "IC-3"}

    def test_a_validation_reject_is_not_reasked(self, monkeypatch):
        """The reject is content the model chose, not structure it
        dropped; re-asking would spend a call to be told again."""
        in_rows = [_row(i) for i in range(4)]
        bad = _reply_row(in_rows[0],
                         what=["One sentence.", "A second sentence."])
        reply = _rows_json([bad] + [_reply_row(r) for r in in_rows[1:]])
        _rows_out, outcome, client, _l = _run(monkeypatch, in_rows, [reply])
        assert len(client.requests) == 1
        assert "IC-0" in outcome.kept


# ---------------------------------------------------------------------------
# 4. the F-107 fallback
# ---------------------------------------------------------------------------

class TestTheUnconstrainedFallback:
    def test_a_rejected_response_format_retries_unconstrained(
            self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        reject = RuntimeError(
            "unsupported parameter 'response_format'; not permitted")
        # `_response_format_rejected` is deliberately narrow: the name in
        # the message AND a 400-shaped exception (a real rejection is a
        # BadRequestError). The double carries the status.
        reject.status_code = 400
        good = _rows_json([_reply_row(r) for r in in_rows])
        _rows_out, outcome, client, _l = _run(monkeypatch, in_rows,
                                              [reject, good])
        assert len(client.requests) == 2
        assert "response_format" not in client.requests[1] or \
            client.requests[1]["response_format"] is None
        assert set(outcome.refined) == {r["id"] for r in in_rows}


# ---------------------------------------------------------------------------
# 5. the reason map — total, and in the user's register
# ---------------------------------------------------------------------------

#: Rows that provoke each of `_validate_row`'s error strings on the
#: refine path (after the 15c auto-route, which repairs rather than
#: rejects the stage↔operator pairing).
PROVOKERS = {
    "Invalid stage": _row(1, stage="XX"),
    "Missing id": _row(1, id=""),
    "Invalid type": _row(1, type="maybe"),
    "Invalid operator": _row(1, operator="fuzzy"),
    "Missing target": _row(1, target=""),
    "Unknown target(s)": _row(1, target="nonexistent_column"),
    "between requires exactly 2 values": _row(
        1, stage="IH", operator="between", what=["2018"], threshold=""),
    "llm requires exactly 1 sentence in what": _row(
        1, what=["One.", "Two."]),
    "threshold must be between 0 and 1": _row(1, threshold="7"),
    "threshold must be a number": _row(1, threshold="high"),
}

BANNED = ["llm", "row", "invalid", "requires exactly"]
OPERATORS_IN_BACKTICKS = ["`equals`", "`contains`", "`regex`", "`in_list`",
                          "`not_in`", "`gte`", "`lte`", "`between`",
                          "`llm`"]


class TestTheReasonMap:
    def test_every_validator_error_maps_to_a_plain_sentence(self):
        """Totality: drive the REAL validator over provoking rows and
        map its REAL strings — no reason may fall through to the
        generic fallback for a known error."""
        mod = _refine()
        inf = _import_plugin("03_harmoniser", "inference")
        for expect, row in PROVOKERS.items():
            errs, _w = inf._validate_row(dict(row), COLS)
            assert any(e.startswith(expect.split("{")[0][:12])
                       or expect.split()[0] in e
                       for e in errs), (expect, errs)
            reason = mod._plain_reason(errs)
            assert reason
            assert reason != mod._GENERIC_REASON, (
                "known error fell through to the generic reason: %r"
                % (errs,))

    def test_the_output_register_is_the_users(self):
        """Adjudication note 2: a leak-proof map that emits
        half-translated jargon satisfies totality and fails the point."""
        mod = _refine()
        inf = _import_plugin("03_harmoniser", "inference")
        reasons = [mod._GENERIC_REASON]
        for row in PROVOKERS.values():
            errs, _w = inf._validate_row(dict(row), COLS)
            reasons.append(mod._plain_reason(errs))
        for reason in reasons:
            low = reason.lower()
            for token in BANNED:
                assert token not in low, (token, reason)
            for op in OPERATORS_IN_BACKTICKS:
                assert op not in reason, (op, reason)

    def test_an_unforeseen_error_gets_the_generic_reason_not_the_raw(self):
        mod = _refine()
        reason = mod._plain_reason(["some new validator message"])
        assert reason == mod._GENERIC_REASON
        assert "some new validator message" not in reason


# ---------------------------------------------------------------------------
# 6. the outcome object — one source for the dialog and the manifest
# ---------------------------------------------------------------------------

class TestTheOutcomeObject:
    def test_kept_reasons_render_in_the_dialog(self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        bad = _reply_row(in_rows[0],
                         what=["One sentence.", "A second sentence."])
        reply = _rows_json([bad] + [_reply_row(r) for r in in_rows[1:]])
        rows, outcome, _c, _l = _run(monkeypatch, in_rows, [reply])
        vr = _vreport()
        report = vr.build_validation_report(
            rows, COLS, show_ok=True, kept_notes=outcome.kept)
        body = report.dialog.body
        assert "kept your original" in body
        assert "IC-0" in body
        assert outcome.kept["IC-0"] in body

    def test_the_manifest_block_is_the_same_object(self, monkeypatch):
        """Adjudication note 3: the kept-with-reason set the user sees
        and the one recorded are THE SAME OBJECT, not two derivations."""
        in_rows = [_row(i) for i in range(4)]
        bad = _reply_row(in_rows[0],
                         what=["One sentence.", "A second sentence."])
        reply = _rows_json([bad] + [_reply_row(r) for r in in_rows[1:]])
        _rows_out, outcome, _c, _l = _run(monkeypatch, in_rows, [reply])
        block = outcome.manifest_block()
        assert block["kept"] is outcome.kept
        assert sorted(block["refined"]) == sorted(outcome.refined)
        assert block["model"] == "m"

    def test_the_manifest_carries_the_refinement_block(self):
        ex = _import_plugin("03_harmoniser", "exporters")
        manifest = ex._build_manifest(
            a_path="a.csv", a_columns=COLS, a_id_col_guess="local_id",
            clean_stats={}, criteria_path="c.txt", criteria_kind="freetext",
            criteria_rows=[_row(1)], criteria_source_text="t",
            wrote_input_errors=False,
            refinement={"model": "m", "refined": ["IC-1"], "kept": {},
                        "repaired": []},
        )
        assert manifest["refinement"]["model"] == "m"
        assert manifest["refinement"]["refined"] == ["IC-1"]

    def test_no_refinement_no_block(self):
        ex = _import_plugin("03_harmoniser", "exporters")
        manifest = ex._build_manifest(
            a_path="a.csv", a_columns=COLS, a_id_col_guess="local_id",
            clean_stats={}, criteria_path="c.txt", criteria_kind="freetext",
            criteria_rows=[_row(1)], criteria_source_text="t",
            wrote_input_errors=False,
        )
        assert "refinement" not in manifest


# ---------------------------------------------------------------------------
# 7. the budget guard, speaking harmoniser language
# ---------------------------------------------------------------------------

class TestTheBudgetGuard:
    def test_an_oversized_table_refuses_before_any_call(self, monkeypatch):
        in_rows = [_row(i, label="L" * 4000, what=["W" * 4000])
                   for i in range(8)]
        with pytest.raises(lc.ContextBudgetExceeded) as ei:
            _run(monkeypatch, in_rows, ["never reached"], window=512)
        assert "criterion" in str(ei.value).lower()
        assert "record" not in str(ei.value).lower()

    def test_a_fitting_table_is_not_refused(self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        rows, _o, client, _l = _run(monkeypatch, in_rows,
                                    _good_scripts(in_rows, 4))
        assert len(client.requests) == 1

    def test_the_noun_parameter_default_is_unchanged(self):
        """The EL/IL message is pinned elsewhere; the noun rides only
        when a caller asks."""
        import inspect
        sig = inspect.signature(lc.check_context_budget)
        assert sig.parameters["noun"].default == "record"


# ---------------------------------------------------------------------------
# 8. F-186 — a failure names its cause, with the numbers
# ---------------------------------------------------------------------------

class TestTheFailureRecord:
    """F-186: truncation, malformation, refusal and a repetition loop
    used to produce one indistinguishable 200-character message that
    misled the first person to read it. Every fact that was in hand at
    the old raise site — finish_reason, all three token counts, the
    reply length, the parse exception's own message — now reaches the
    diagnostics record and the log; the dialog keeps the plain
    sentence."""

    def test_an_unusable_chunk_records_all_four_facts(self, monkeypatch):
        in_rows = [_row(i) for i in range(4)]
        bad = '{"rows": [{"id": "IC-0", "type": '
        _rows_out, outcome, _c, logs = _run(monkeypatch, in_rows,
                                            [bad, bad])
        recs = [d for d in outcome.diagnostics if "unusable reply" in d]
        assert recs, outcome.diagnostics
        rec = recs[0]
        assert "finish_reason=stop" in rec
        assert "prompt_tokens=100" in rec
        assert "completion_tokens=50" in rec
        assert "total_tokens=150" in rec
        assert "reply_chars=%d" % len(bad) in rec
        assert any(rec in l for l in logs), "the record reaches the log"

    def test_the_parse_exception_survives_with_its_position(
            self, monkeypatch):
        """The old message quoted 200 chars ending mid-token and threw
        the JSONDecodeError away; the error's own message names the
        offending position and now survives."""
        in_rows = [_row(i) for i in range(4)]
        bad = '{"rows": [{"id": "IC-0", "type": '
        _rows_out, outcome, _c, _l = _run(monkeypatch, in_rows,
                                          [bad, bad])
        rec = [d for d in outcome.diagnostics if "unusable reply" in d][0]
        assert "parse_error=" in rec
        assert "JSONDecodeError" in rec or "Expecting" in rec

    def test_wrong_shape_is_distinguishable_from_malformed(
            self, monkeypatch):
        """Valid JSON with no rows list is a different failure from
        JSON that never parsed, and the record must say which."""
        in_rows = [_row(i) for i in range(4)]
        wrong_shape = json.dumps({"verdict": "looks fine"})
        _rows_out, outcome, _c, _l = _run(monkeypatch, in_rows,
                                          [wrong_shape, wrong_shape])
        rec = [d for d in outcome.diagnostics if "unusable reply" in d][0]
        assert "carried no rows list" in rec
        assert "JSONDecodeError" not in rec

    def test_the_dialog_stays_in_the_users_register(self, monkeypatch):
        """The numbers go to the log; the dialog says what happened in
        plain words (the adjudicated split of F-186's remedy)."""
        in_rows = [_row(i) for i in range(4)]
        bad = '{"rows": [{"id": "IC-0", '
        rows, outcome, _c, _l = _run(monkeypatch, in_rows, [bad, bad])
        vr = _vreport()
        report = vr.build_validation_report(
            rows, COLS, show_ok=True, kept_notes=outcome.kept)
        body = report.dialog.body
        assert "kept your original" in body
        assert "finish_reason" not in body
        assert "JSONDecodeError" not in body
