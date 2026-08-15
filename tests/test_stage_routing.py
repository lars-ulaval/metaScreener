# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""test_stage_routing.py — F-65: the router, its net, and the refiner's
named repair (wave 15c).

A deterministic operator belongs at the heuristic stage of its criterion's
type; `llm` belongs at EL/IL. Until this wave the translator's branch 6
paired `contains` with IL/EL (the only branch that did), `_validate_row`
checked stage and operator separately and never together, and the LLM
refiner — whose prompt says "If unsure, prefer operator=llm and stage
IL/EL" — rebuilt stages from model output behind guardrails that passed
the pairing clean. The result is F-65's register row: IC-5 marked
UNCERTAIN for every record of every run, never evaluated, PASS_CLEAN
structurally unreachable.

Every fixture that can come from the real producer does: the router tests
drive `_parse_free_text_criteria` → `_infer_criterion_details`; the chain
test runs the translator's own output over the full reference corpus
through the real parser, loader, evaluator and runner.
"""
import threading

from conftest import AGGREGATE_CSV, IC_EC_FILE, _import_plugin, get_harmoniser


def _inference():
    return _import_plugin("03_harmoniser", "inference")


def _hparser():
    return _import_plugin("03_harmoniser", "parser")


def _linter():
    return _import_plugin("03_harmoniser", "linter")


def _refine():
    return _import_plugin("03_harmoniser", "llm_refine")


def _vreport():
    return _import_plugin("03_harmoniser", "validate_report")


def _rule_for(label, crit_type="include", crit_id="X-1"):
    """The rule the translator emits for one sentence, real producer."""
    h = get_harmoniser()
    a_columns, text_stats = h._load_a_header_and_stats(str(AGGREGATE_CSV))
    default_text_target = h._get_best_text_targets(a_columns, text_stats)
    default_text_target, _ = h._canonicalize_targets(default_text_target,
                                                     a_columns)
    inferred = h._infer_criterion_details(
        crit_id=crit_id, crit_type=crit_type, label=label,
        a_columns=list(a_columns), default_text_target=default_text_target,
    )
    return (inferred["stage"], inferred["operator"],
            inferred["target"], list(inferred["what"]))


IC5_LABEL = ("The title, abstract, or keywords mention training OR "
             "vocational OR workplace.")


class TestTheRouterRule:
    def test_a_keyword_include_routes_to_ih(self):
        stage, op, target, what = _rule_for(IC5_LABEL, "include")
        assert (stage, op) == ("IH", "contains")
        assert target == "title,abstract,keywords"
        assert what == ["training", "vocational", "workplace"]

    def test_a_keyword_exclude_routes_to_eh(self):
        stage, op, _t, _w = _rule_for(
            'The title or abstract mentions cadaver.', "exclude")
        assert (stage, op) == ("EH", "contains")

    def test_the_semantic_default_still_routes_to_il(self):
        stage, op, _t, _w = _rule_for(
            "The paper considers immersive virtual reality.", "include")
        assert (stage, op) == ("IL", "llm")


class TestTheVocabularyHome:
    """F-109: one map, hoisted to the package's vocabulary module, with
    the linter re-exporting rather than re-typing."""

    def test_parser_owns_the_map_and_linter_reexports_it(self):
        p, l = _hparser(), _linter()
        assert p.executable_operators("IL") == ("llm",)
        assert p.executable_operators("EL") == ("llm",)
        assert "contains" in p.executable_operators("IH")
        assert l.executable_operators is p.executable_operators
        assert l._EXECUTABLE_BY_STAGE is p.EXECUTABLE_BY_STAGE


def _row(**kw):
    base = {"stage": "IH", "id": "IC-9", "type": "include",
            "scope": "metadata", "label": "t", "operator": "contains",
            "target": "title", "what": ["x"], "threshold": "",
            "enabled": True, "source_text": "t"}
    base.update(kw)
    return base


COLS = ["title", "abstract", "keywords", "lang", "year"]


class TestTheCrossCheckError:
    """The net over every producer: an operator the stage cannot execute
    is an authoring-time ERROR — the deferred half of 13c's decision."""

    def test_contains_at_il_is_an_error(self):
        errs, _w = _inference()._validate_row(
            _row(stage="IL", threshold="0.60"), COLS)
        assert any("cannot execute" in e for e in errs), errs

    def test_llm_at_eh_is_an_error(self):
        errs, _w = _inference()._validate_row(
            _row(stage="EH", operator="llm", what=["a sentence"]), COLS)
        assert any("cannot execute" in e for e in errs), errs

    def test_contains_at_ih_is_clean(self):
        errs, _w = _inference()._validate_row(_row(), COLS)
        assert errs == []

    def test_llm_at_il_is_clean(self):
        errs, _w = _inference()._validate_row(
            _row(stage="IL", operator="llm", what=["a sentence"],
                 threshold="0.60"), COLS)
        assert errs == []


class TestTheRefinerAutoRoute:
    """The model may propose the forbidden pairing; the refiner repairs
    it by the router's own rule and NAMES the repair — it must reach the
    completion dialog, not only the log."""

    def _refined(self, monkeypatch, model_rows, in_rows):
        # Wave 15d flipped the return contract in the open: _llm_refine
        # returns (rows, RefineOutcome), the outcome being the one
        # object the dialog and the manifest both render from; the
        # repair notes ride outcome.repairs unchanged.
        lr = _refine()
        monkeypatch.setattr(lr, "_call_openai_json",
                            lambda **_kw: ({"rows": model_rows}, {}))
        rows, outcome = lr._llm_refine(in_rows, "text", COLS, model="m",
                                       log=lambda *_a: None)
        return rows, outcome.repairs

    def test_contains_at_il_is_restaged_to_ih_and_named(self, monkeypatch):
        in_rows = [_row()]
        model = [{"id": "IC-9", "type": "include", "stage": "IL",
                  "label": "t", "operator": "contains", "target": "title",
                  "what": ["x"], "threshold": "0.60", "enabled": True}]
        rows, repairs = self._refined(monkeypatch, model, in_rows)
        assert rows[0]["stage"] == "IH"
        assert rows[0]["threshold"] == ""
        assert len(repairs) == 1
        assert "IC-9" in repairs[0] and "IH" in repairs[0]

    def test_llm_at_eh_is_restaged_to_el_and_named(self, monkeypatch):
        in_rows = [_row(id="EC-9", type="exclude", stage="EL",
                        operator="llm", what=["a sentence"],
                        threshold="0.60")]
        model = [{"id": "EC-9", "type": "exclude", "stage": "EH",
                  "label": "t", "operator": "llm", "target": "title",
                  "what": ["a sentence"], "threshold": "", "enabled": True}]
        rows, repairs = self._refined(monkeypatch, model, in_rows)
        assert rows[0]["stage"] == "EL"
        assert rows[0]["threshold"] != ""
        assert len(repairs) == 1
        assert "EC-9" in repairs[0]

    def test_a_consistent_reply_makes_no_repairs(self, monkeypatch):
        in_rows = [_row()]
        model = [{"id": "IC-9", "type": "include", "stage": "IH",
                  "label": "t", "operator": "contains", "target": "title",
                  "what": ["x"], "threshold": "", "enabled": True}]
        rows, repairs = self._refined(monkeypatch, model, in_rows)
        assert rows[0]["stage"] == "IH"
        assert repairs == []


class TestTheDialogNamesTheRepair:
    """The repair reaches the validate surface like every other note."""

    def test_repair_notes_render_in_the_dialog(self):
        vr = _vreport()
        report = vr.build_validation_report(
            [_row()], COLS, show_ok=True,
            repair_notes=("IC-9: the model put deterministic operator "
                          "'contains' at IL; re-staged to IH",))
        assert report.ok is True
        assert report.dialog is not None
        assert "re-staged to IH" in report.dialog.body

    def test_no_notes_no_new_section(self):
        vr = _vreport()
        report = vr.build_validation_report([_row()], COLS, show_ok=True)
        assert report.ok is True
        assert "adjustment" not in (report.dialog.body if report.dialog
                                    else "")


class TestTheChainAsRouted:
    """The deterministic funnel, translator output over the reference
    corpus through the real runner. Verified live at wave 15c: routing
    IC-5 to IH under the F-204 union evaluator gives 776 → EH OUT 16 →
    760 → IH OUT 738 → 22. Pinned so the next translator or evaluator
    change shows its corpus effect here, in the open."""

    def test_the_funnel(self, tmp_path):
        import test_harmoniser_regression as thr
        from plugins._common.parser import (_parse_csv_tolerant_text,
                                            _load_criteria_from_text,
                                            ParseReport)
        from plugins._common.runner import run_screen

        out = tmp_path / "criteria.csv"
        thr._harmonise_to_csv(out)
        crit_text = out.read_text(encoding="utf-8-sig")

        corpus = AGGREGATE_CSV.read_bytes().decode("utf-8-sig")
        parse = _parse_csv_tolerant_text(corpus)
        assert len(parse.rows) == 776 and not parse.skipped

        ev = threading.Event()
        _f, surv_eh, c_eh, _i, _r, cancelled = run_screen(
            parse, _load_criteria_from_text(crit_text, "EH"), ev,
            stage="EH")
        assert not cancelled
        assert (c_eh["OUT"], len(surv_eh)) == (16, 760)

        pr = ParseReport(header=parse.header, rows=surv_eh, skipped=[])
        _f, surv_ih, c_ih, imp, _r, cancelled = run_screen(
            pr, _load_criteria_from_text(crit_text, "IH"), ev, stage="IH")
        assert not cancelled
        assert (c_ih["OUT"], len(surv_ih)) == (738, 22)
        assert imp["IC-5"]["met"] == 70
        assert imp["IC-5"]["failed"] == 690
