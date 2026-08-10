# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_batch_size.py — D6: the number, and what may and may not be said
about it.

Why the wording is tested at all
--------------------------------
Because what the tooltip must **not** say is the load-bearing part, and a
sentence is as shippable as a line of code.

* **It must not read as a safety measure.** The correctness defect in
  this neighbourhood is F-86 — a response naming a record from another
  batch, whose quote then validated against *that* record's text. It is
  **closed**, in the engine, since wave 7, and it fired at
  ``batch_size = 1`` as readily as at 50, because the acceptance guard
  admitted any known ``a_id`` whatever batch it came from. A tooltip
  implying that a smaller batch makes a run safer would be false
  reassurance about a defect that is already fixed and was never about
  this number.
* **It must not imply the cache is affected.** F-101: the cache key
  hashes a synthetic one-item prompt, so ``batch_size`` is invisible to
  it. Not saying so is its own harm — "will this throw away my cached
  decisions?" is the reasonable fear that stops a user touching the box.
* **It must not claim anything about how well a local model screens.**
  That needs a live measurement and is wave 12's.

The regression this file also pins
----------------------------------
Session A shipped ``defaults()["batch_size"] = 5`` and nothing read it.
Session C made the store's batch size live, and that value would then
have dropped **every** stage — including one running against OpenAI —
from the module default of 50 to 5: ten times the requests, silently.
Measured before it shipped. ``defaults()`` now says ``None`` — *nobody
has chosen* — and the provider suggests.
"""
import importlib.util
import sys

import pytest

from conftest import PROJECT_ROOT

import plugins._common.stage_state as ss


def _load(name, relpath):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, str(PROJECT_ROOT.joinpath(*relpath.split("/")))
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load("_settings_for_batch", "plugins/_common/settings.py")

KEYLESS = ("local", "custom")
KEYED = ("openai", "", "something-new")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return S


# ---------------------------------------------------------------------------
# The number
# ---------------------------------------------------------------------------

class TestTheNumber:

    @pytest.mark.parametrize("provider", KEYLESS)
    def test_a_local_provider_gets_a_small_batch(self, provider):
        assert ss.recommended_batch_size(provider) == ss.LOCAL_BATCH_SIZE

    @pytest.mark.parametrize("provider", KEYED)
    def test_everything_else_gets_no_suggestion(self, provider):
        """``None`` means the stage's own module default answers. A
        number here would be this module deciding something it cannot
        see the inputs for."""
        assert ss.recommended_batch_size(provider) is None

    def test_the_value_is_inside_the_range_the_coordinator_specified(self):
        low, high = ss.LOCAL_BATCH_RANGE
        assert low <= ss.LOCAL_BATCH_SIZE <= high
        assert (low, high) == (5, 10)

    @pytest.mark.parametrize("plugin_dir", ["06_el", "07_il"])
    def test_it_is_a_large_reduction_from_the_stage_default(self, plugin_dir):
        """The point of D6: today's 50 asks a model for fifty JSON objects
        in one reply. Read from the stage module rather than restated, so
        a later change to either number cannot quietly make this a
        rounding difference."""
        import ast
        src = (PROJECT_ROOT / "plugins" / plugin_dir / "plugin.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        default = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "DEFAULT_BATCH_SIZE"
                       for t in node.targets):
                continue
            # int(os.environ.get("SCREENA_*_BATCH_SIZE", "50"))
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                        and sub.value.isdigit():
                    default = int(sub.value)
        assert default == 50, (plugin_dir, default)
        assert ss.LOCAL_BATCH_SIZE * 5 <= default


# ---------------------------------------------------------------------------
# The regression session C introduced and caught
# ---------------------------------------------------------------------------

class TestTheStoreDoesNotImposeABatchSizeOnEveryone:

    def test_the_shipped_default_is_unchosen_rather_than_five(self):
        assert S.defaults()["batch_size"] is None, (
            "a concrete number here reaches every stage, including one "
            "running against OpenAI, and this file cannot see the provider"
        )

    def test_a_fresh_install_offers_no_batch_size(self, store):
        assert S.resolve_stage(S.load_settings(), "EL").batch_size is None

    @pytest.mark.parametrize("provider", KEYED)
    def test_a_keyed_provider_still_offers_none(self, store, provider):
        """The regression, as an assertion: an OpenAI stage must not be
        silently dropped to a local model's batch size."""
        S.update_settings(provider=provider, api_key="sk-x")
        assert S.resolve_stage(S.load_settings(), "EL").batch_size is None

    @pytest.mark.parametrize("provider", KEYLESS)
    def test_a_keyless_provider_offers_the_small_one(self, store, provider):
        S.update_settings(provider=provider,
                          endpoint="http://localhost:11434/v1")
        assert S.resolve_stage(S.load_settings(), "EL").batch_size == \
            ss.LOCAL_BATCH_SIZE

    def test_an_explicit_choice_beats_the_suggestion(self, store):
        S.update_settings(provider="local",
                          endpoint="http://localhost:11434/v1",
                          batch_size=25)
        assert S.resolve_stage(S.load_settings(), "EL").batch_size == 25

    def test_a_stage_override_beats_both(self, store):
        S.update_settings(provider="local",
                          endpoint="http://localhost:11434/v1")
        S.set_stage_override("EL", batch_size=12)
        assert S.resolve_stage(S.load_settings(), "EL").batch_size == 12
        assert S.resolve_stage(S.load_settings(), "IL").batch_size == \
            ss.LOCAL_BATCH_SIZE


# ---------------------------------------------------------------------------
# The wording
# ---------------------------------------------------------------------------

#: Phrases that would turn a throughput knob into a safety claim. The
#: register carries this argument explicitly, so it is pinned rather than
#: left to a reviewer to notice.
FALSE_REASSURANCE = (
    "safer", "safest", "more reliable", "prevents", "guarantee",
    "avoids errors", "protects", "reduces the risk", "less risk",
    "more accurate", "improves accuracy",
)


#: The one sanctioned use of the word, and it is a **denial**. Required
#: verbatim, then removed before the forbidden list is applied — a blunt
#: substring check flags the tooltip's own correction, and a guard that
#: fires on the sentence it exists to demand gets deleted rather than
#: obeyed.
DENIAL = "A smaller batch does not make a run safer"


class TestTheWordingDoesNotOverclaim:

    @pytest.mark.parametrize("provider", KEYLESS + KEYED)
    def test_the_denial_is_present_verbatim(self, provider):
        assert DENIAL in ss.batch_size_tooltip(provider)

    @pytest.mark.parametrize("provider", KEYLESS + KEYED)
    def test_it_never_says_a_smaller_batch_is_safer(self, provider):
        text = ss.batch_size_tooltip(provider).lower()
        remainder = text.replace(DENIAL.lower(), "")
        for phrase in FALSE_REASSURANCE:
            assert phrase not in remainder, (
                f"provider={provider!r}: {phrase!r} reframes a throughput "
                f"knob as a safety one"
            )

    @pytest.mark.parametrize("provider", KEYLESS + KEYED)
    def test_it_says_outright_that_this_is_a_quality_setting(self, provider):
        text = ss.batch_size_tooltip(provider)
        assert "QUALITY setting, not a correctness one" in text

    @pytest.mark.parametrize("provider", KEYLESS + KEYED)
    def test_it_names_f_86_as_closed_and_as_firing_at_one(self, provider):
        """The specific denial. Naming the defect without saying it is
        closed, or without saying it fired at 1, would leave the reader
        with exactly the wrong impression."""
        text = ss.batch_size_tooltip(provider)
        assert "F-86" in text
        assert "batch size of 1" in text
        assert "closed" in text

    @pytest.mark.parametrize("provider", KEYLESS + KEYED)
    def test_it_says_the_cache_is_not_invalidated(self, provider):
        """F-101, said where the user needs it — beside the box they are
        about to change."""
        text = ss.batch_size_tooltip(provider)
        assert "does not invalidate your cache" in text
        assert "F-101" in text

    @pytest.mark.parametrize("provider", KEYLESS + KEYED)
    def test_it_makes_no_claim_about_local_screening_quality(self, provider):
        """Out of scope by instruction; wave 12 needs a live measurement.
        The claim made is narrow: a shorter list is easier to keep track
        of. Anything about *screening* quality would be unearned."""
        text = ss.batch_size_tooltip(provider).lower()
        for phrase in ("as good as", "comparable to", "screens well",
                       "as accurate", "quality of the screening",
                       "matches gpt", "as well as openai"):
            assert phrase not in text, phrase

    def test_the_local_wording_names_the_number_it_drops_to(self):
        assert str(ss.LOCAL_BATCH_SIZE) in ss.batch_size_tooltip("local")

    def test_the_hosted_wording_says_where_the_drop_would_apply(self):
        text = ss.batch_size_tooltip("openai")
        assert "local provider is selected" in text
        assert str(ss.LOCAL_BATCH_SIZE) in text

    @pytest.mark.parametrize("provider", KEYLESS + KEYED)
    def test_it_explains_what_a_batch_actually_is(self, provider):
        """A reason a user cannot act on is not a reason. The mechanism —
        one JSON object per record in a single reply — is the part that
        makes 'the model loses track' mean something."""
        text = ss.batch_size_tooltip(provider)
        assert "one JSON object per record" in text

    def test_the_two_wordings_differ(self):
        assert ss.batch_size_tooltip("local") != ss.batch_size_tooltip("openai")


class TestTheWordingIsDecidedWithoutTk:
    """The division that makes the paragraph above assertable at all: the
    text is decided in ``stage_state`` and handed to a widget that holds
    no logic. A tooltip whose wording lived in the View could not be
    checked in this suite, because the conftest replaces tkinter."""

    def test_stage_state_imports_no_tk(self):
        import ast
        tree = ast.parse((PROJECT_ROOT / "plugins" / "_common" /
                          "stage_state.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "tkinter" not in imported

    def test_the_tooltip_widget_decides_no_wording(self):
        """It may format and place; it may not compose."""
        import ast
        tree = ast.parse((PROJECT_ROOT / "plugins" / "_common" /
                          "widgets.py").read_text(encoding="utf-8"))
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "Tooltip")
        for node in ast.walk(cls):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # docstrings only; no user-facing sentence may originate here
                assert len(node.value) < 40 or node.value.strip().startswith(
                    ("A hover", "Replace", "Long enough")), node.value[:60]

    @pytest.mark.parametrize("rel", ["plugins/06_el/ui.py",
                                     "plugins/07_il/ui.py"])
    def test_both_views_attach_it_to_the_batch_field(self, rel):
        src = PROJECT_ROOT.joinpath(*rel.split("/")).read_text(
            encoding="utf-8")
        assert "Tooltip(self.ent_batch" in src
        assert "batch_size_tooltip(" in src

    @pytest.mark.parametrize("rel", ["plugins/06_el/ui.py",
                                     "plugins/07_il/ui.py"])
    def test_a_provider_change_refreshes_the_wording(self, rel):
        """A tooltip explaining a number the box no longer shows is worse
        than none."""
        import ast
        tree = ast.parse(PROJECT_ROOT.joinpath(*rel.split("/")).read_text(
            encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "on_provider_changed")
        assert "batch_size_tooltip" in ast.unparse(fn), rel
