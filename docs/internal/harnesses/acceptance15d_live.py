# -*- coding: utf-8 -*-
"""Wave 15d live acceptance, conftest-free: the REAL settings store
resolves (provider=local -> localhost), the REAL modules run, calls are
counted on the REAL client. Budget: 12 Ollama calls."""
import importlib.util
import json, sys, tempfile, types, zipfile
from pathlib import Path

REPO = Path(r"S:\Alejandro_\projet julien (prisma-hub)\prisma-hub_v3_repo")
sys.path.insert(0, str(REPO))

# package shims for the digit-named subpackage (the linter test's recipe)
for name, path in (
        ("plugins.03_harmoniser", REPO / "plugins" / "03_harmoniser"),):
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod


def _load(sub):
    spec = importlib.util.spec_from_file_location(
        f"plugins.03_harmoniser.{sub}",
        str(REPO / "plugins" / "03_harmoniser" / f"{sub}.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


hp = _load("parser")
inf = _load("inference")
lr = _load("llm_refine")
vr = _load("validate_report")
ex = _load("exporters")
bundle_mod = _load("bundle")

import plugins._common.llm_client as lc

# sanity BEFORE any call: where will this go?
endpoint = lc.resolve_openai_base_url(lr.STAGE)
window = lc.resolve_context_window(lr.STAGE)
print("resolved endpoint: %s   window: %d" % (endpoint, window))
assert "localhost" in endpoint or "127.0.0.1" in endpoint, (
    "refusing to run the live half against a non-local endpoint: %s"
    % endpoint)

BUDGET = 12
calls = {"n": 0}
_real_builder = lc._openai_client_for


class _CountingClient:
    def __init__(self, real):
        outer_real = real

        class _Completions:
            def create(self, **kw):
                calls["n"] += 1
                assert calls["n"] <= BUDGET, "live budget exceeded"
                return outer_real.chat.completions.create(**kw)

        self.chat = type("Chat", (), {"completions": _Completions()})()


lc._openai_client_for = lambda *a, **k: _CountingClient(_real_builder(*a, **k))

# the GUI's own deterministic producer, module functions directly
AGG = REPO / "samples" / "20260122_1654_aggregate.csv"
ICEC = REPO / "samples" / "ic_ec_12.txt"
a_columns, text_stats = hp._load_a_header_and_stats(str(AGG))
dtt = hp._get_best_text_targets(a_columns, text_stats)
dtt, _ = hp._canonicalize_targets(dtt, a_columns)
full_text = ICEC.read_text(encoding="utf-8-sig")

rows_in = []
for crit_id, crit_type, label, source_line in \
        hp._parse_free_text_criteria(full_text):
    inferred = inf._infer_criterion_details(
        crit_id=crit_id, crit_type=crit_type, label=label,
        a_columns=list(a_columns), default_text_target=dtt)
    stage = inferred["stage"]
    rows_in.append({
        "stage": stage, "id": crit_id, "type": crit_type,
        "scope": "metadata", "label": label,
        "operator": inferred["operator"], "target": inferred["target"],
        "what": inferred["what"],
        "threshold": (f"{inf.DEFAULT_THRESHOLD:.2f}"
                      if stage in {"EL", "IL"} else ""),
        "enabled": True, "source_text": source_line,
    })
print("deterministic rows: %d  %s" % (len(rows_in),
                                      [r["id"] for r in rows_in]))

MODEL = "qwen2.5:7b"
results = []
for run_no in (1, 2):
    logs = []
    before = calls["n"]
    rows_out, outcome = lr._llm_refine(
        [dict(r) for r in rows_in], full_text, list(a_columns),
        model=MODEL, log=logs.append)
    spent = calls["n"] - before
    ids_ok = [r["id"] for r in rows_out] == [r["id"] for r in rows_in]
    by_id = {r["id"]: r for r in rows_in}
    kept_ok = all(rows_out[i] == by_id[r["id"]]
                  for i, r in enumerate(rows_out)
                  if r["id"] in outcome.kept)
    print("\n=== RUN %d: calls=%d  ids_in_order=%s  kept_rows_byte_ok=%s"
          % (run_no, spent, ids_ok, kept_ok))
    print("  refined=%s" % outcome.refined)
    print("  kept=%s" % json.dumps(outcome.kept, ensure_ascii=False))
    print("  repaired=%s" % outcome.repaired)
    for l in logs:
        if ("chunk" in l or "re-ask" in l or "repair" in l
                or "unusable" in l or "kept" in l or "rejected" in l):
            print("  log: %s" % l)
    report = vr.build_validation_report(
        rows_out, list(a_columns), show_ok=True,
        kept_notes=outcome.kept or None,
        repair_notes=tuple(outcome.repairs))
    print("  DIALOG kind=%s title=%s" % (report.dialog.kind,
                                         report.dialog.title))
    for line in report.dialog.body.splitlines():
        print("    | " + line)
    results.append((rows_out, outcome))

same = ([r["id"] for r in results[0][0]] == [r["id"] for r in results[1][0]]
        and sorted(results[0][1].refined) == sorted(results[1][1].refined)
        and results[0][1].kept == results[1][1].kept)
print("\nstable across runs (ids, refined set, kept map): %s" % same)
diffs = [rid for rid, (a, b) in
         {r["id"]: (results[0][0][i], results[1][0][i])
          for i, r in enumerate(results[0][0])}.items() if a != b]
print("rows differing between runs: %s" % (diffs or "none"))

rows_out, outcome = results[1]
with tempfile.TemporaryDirectory() as td:
    zp = str(Path(td) / "acceptance_bundle.zip")
    bundle_mod.export_screen_a_bundle(
        rows=rows_out, a_path=str(AGG), a_columns=list(a_columns),
        a_id_col_guess="local_id", criteria_path=str(ICEC),
        criteria_kind="freetext", criteria_source_text=full_text,
        zip_out_path=zp, refinement=outcome.manifest_block())
    with zipfile.ZipFile(zp) as zf:
        name = [n for n in zf.namelist()
                if n.endswith("manifest.json")][0]
        man = json.loads(zf.read(name).decode("utf-8"))
    blk = man.get("refinement")
    print("\nmanifest refinement block present: %s" % bool(blk))
    if blk:
        print("  model=%s refined=%s repaired=%s"
              % (blk.get("model"), blk.get("refined"),
                 blk.get("repaired")))
        print("  kept identical to dialog's: %s"
              % (blk.get("kept") == outcome.kept))

print("\nTOTAL LIVE CALLS: %d of %d budgeted" % (calls["n"], BUDGET))
