
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_cache_key.py — F-01: the LLM cache key must cover everything the
model actually sees.

The defect this pins
--------------------
The key used to be composed from an enumerated list of fields:

    prompt_version | model | cid | a_id | text_hash | trunc_chars

Of the criterion, only its *id* appeared. But the rendered prompt carries
``type``, ``operator``, ``target``, ``what``, ``label`` and ``threshold``
(plugins/06_el/prompt.py:42-51). Editing a criterion's wording while
keeping its id therefore produced a cache *hit*: every record was served
the previous criterion's answer, complete with evidence quotes produced
against text the model never saw on that run, and the UI reported a
perfectly normal ``cache_hits=N``.

The structural fix is to key on a hash of the fully-rendered prompt
string (plus model and temperature) rather than on a hand-maintained list
of fields. Temperature and prompt version had each been bolted onto that
list in separate earlier commits; this test file exists so the third
omission cannot happen silently.

``test_edited_criterion_text_changes_key`` is the bug. The rest are the
properties that must not regress while fixing it.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from conftest import get_el, get_il

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures: a criterion pack and an item in the shape run_el_screen builds
# ---------------------------------------------------------------------------

def _criterion(**over):
    """A criterion pack in the shape run_el_screen/run_il_screen assemble
    before calling the prompt builder."""
    base = {
        "id": "EC-1",
        "type": "exclude",
        "operator": "llm",
        "target": "title,abstract",
        "what": ["not an empirical study"],
        "how": "llm",
        "label": "Exclude non-empirical work",
        "threshold": 0.6,
    }
    base.update(over)
    return base


def _item(**over):
    base = {
        "a_id": "rec_001",
        "title": "Virtual reality in nurse education",
        "abstract": "We report a randomised trial of VR training.",
        "keywords": "VR; nursing; education",
    }
    base.update(over)
    return base


# A fixed endpoint for every key computed here (F-89).
#
# Passed explicitly rather than left to resolve from os.environ, so these
# assertions cannot change meaning on a machine that happens to export
# OPENAI_BASE_URL. `_cache_key` takes the endpoint as a parameter for
# exactly this reason: the resolution is the stage engine's job, and a
# hash function that reads the environment is a hash function whose
# fixtures are the developer's shell.
_ENDPOINT = "https://api.openai.com/v1"
_OTHER_ENDPOINT = "http://localhost:11434/v1"


def _key(mod, **over):
    kw = dict(model="gpt-4o-mini", criterion=_criterion(),
              item=_item(), trunc_chars=4000, endpoint=_ENDPOINT)
    crit_over = over.pop("criterion_over", None)
    item_over = over.pop("item_over", None)
    if crit_over:
        kw["criterion"] = _criterion(**crit_over)
    if item_over:
        kw["item"] = _item(**item_over)
    kw.update(over)
    return mod._cache_key(**kw)


# ---------------------------------------------------------------------------
# The bug
# ---------------------------------------------------------------------------

class TestEditedCriterionContentInvalidatesCache:
    """Same criterion id, different criterion content → different key.

    This is F-01. Before the fix both sides of each assertion collapsed to
    the same key, because only ``id`` reached the hash.
    """

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    @pytest.mark.parametrize("field,edited", [
        ("what", ["not a randomised controlled trial"]),
        ("label", "Exclude non-empirical work (revised wording)"),
        ("type", "include"),
        ("operator", "regex"),
        ("target", "abstract"),
        ("threshold", 0.9),
    ])
    def test_edited_criterion_text_changes_key(self, mod_getter, field, edited):
        mod = mod_getter()
        k_before = _key(mod)
        k_after = _key(mod, criterion_over={field: edited})
        assert k_before != k_after, (
            f"F-01: editing criterion field {field!r} while keeping the same "
            f"id produced an identical cache key. The next run would serve "
            f"every record the previous criterion's answer, with evidence "
            f"quotes taken against text the model never saw this run."
        )


class TestEndpointIsInTheKey:
    """F-89: **who answers** must reach the key, not only what is asked.

    The key hashed ``{prompt_version, model, temperature, prompt}``.
    ``base_url`` appeared nowhere and no repository code read
    ``OPENAI_BASE_URL`` at all, so a model name served by OpenAI and the
    same name served by Ollama were one namespace.

    This is F-01's exact failure shape displaced onto the provider axis.
    ``_cache_key``'s post-F-01 argument — "anything that changes what the
    model sees changes the key automatically" — is true, and it does not
    cover who is being asked. The trigger is not exotic: it is the literal
    ``.env`` edit the README's "Using local LLM providers" section
    instructs, and the same section tells the user to leave the Model
    field alone, which is the maximally ambiguous configuration.
    """

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_endpoint_change_changes_key(self, mod_getter):
        """**This is F-89.**

        Before the fix both sides collapsed to one key, so following the
        README's Ollama recipe produced 100% cache hits and OpenAI's
        answers, logged as a normal ``cache_hits=N``, with no trace in any
        artefact.
        """
        mod = mod_getter()
        assert _key(mod) != _key(mod, endpoint=_OTHER_ENDPOINT), (
            "F-89: the same model name at two different endpoints produced "
            "one cache key. A run switched to a local provider is served "
            "the previous provider's answers and reports a healthy run."
        )

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_two_local_servers_on_different_ports_differ(self, mod_getter):
        """The comparison the maintainer expects to run.

        A coarse "local vs remote" label could not distinguish these, which
        is one of the two reasons the endpoint is hashed verbatim.
        """
        mod = mod_getter()
        assert (_key(mod, endpoint="http://localhost:11434/v1")
                != _key(mod, endpoint="http://localhost:8080/v1"))

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_same_endpoint_same_key(self, mod_getter):
        """The endpoint discriminates and nothing more — it must not make
        the key unstable for an unchanged configuration."""
        mod = mod_getter()
        assert _key(mod, endpoint=_ENDPOINT) == _key(mod, endpoint=_ENDPOINT)

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_endpoint_is_hashed_verbatim_not_reduced(self, mod_getter):
        """Two hosts that differ only below a coarse label must differ.

        Pins the decision recorded in ``_cache_key``'s docstring: the
        resolved endpoint is hashed as-is, not digested and not reduced to
        a category. A digest of a short internal hostname is a
        discriminator rather than a secret, so it would buy privacy it
        cannot deliver while destroying cross-machine comparability.
        """
        mod = mod_getter()
        assert (_key(mod, endpoint="http://gpu-01.lan:8080/v1")
                != _key(mod, endpoint="http://gpu-02.lan:8080/v1"))

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_endpoint_is_required(self, mod_getter):
        """Omitting it must be a TypeError, not a silent default.

        A default would let a future call site forget the endpoint and
        quietly reintroduce F-89 for that path, with the suite green —
        which is how the enumerated key accreted its omissions in the
        first place (F-01).
        """
        mod = mod_getter()
        with pytest.raises(TypeError):
            mod._cache_key(model="gpt-4o-mini", criterion=_criterion(),
                           item=_item(), trunc_chars=4000)

    def test_the_key_does_not_read_the_environment(self, monkeypatch):
        """The endpoint arrives as an argument, so the key is a pure
        function of its inputs.

        If ``_cache_key`` read ``os.environ`` itself, golden byte-identity
        would become environment-dependent and neither
        ``test_key_stable_across_processes`` (which copies ``os.environ``
        wholesale) nor CI could detect the instability — the failure would
        show up only on the machine of the person developing the feature.
        """
        el = get_el()
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        unset = _key(el)
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
        assert _key(el) == unset


# ---------------------------------------------------------------------------
# Properties that must not regress
# ---------------------------------------------------------------------------

class TestCacheKeySanity:

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_same_content_different_cid_changes_key(self, mod_getter):
        """Sanity: the id still participates."""
        mod = mod_getter()
        assert _key(mod) != _key(mod, criterion_over={"id": "EC-2"})

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_deterministic_within_process(self, mod_getter):
        mod = mod_getter()
        assert _key(mod) == _key(mod)

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_model_change_changes_key(self, mod_getter):
        mod = mod_getter()
        assert _key(mod) != _key(mod, model="gpt-4o")

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_temperature_change_changes_key(self, mod_getter):
        """0.0 is the default and must stay the default; anything else is a
        different key so a warm run cannot silently reuse a cold one."""
        mod = mod_getter()
        k_default = _key(mod)
        assert k_default == _key(mod, temperature=0.0)
        assert k_default != _key(mod, temperature=0.7)

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_record_text_change_changes_key(self, mod_getter):
        mod = mod_getter()
        assert _key(mod) != _key(mod, item_over={"abstract": "Something else."})
        assert _key(mod) != _key(mod, item_over={"a_id": "rec_002"})

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_non_target_field_change_still_changes_key(self, mod_getter):
        """The prompt ships title, abstract AND keywords regardless of which
        fields the criterion targets, so all three must reach the key.

        The old key hashed only the *target* fields, which was the same
        defect in a second place: with target='title,abstract', editing a
        record's keywords changed the model's input but not the key.
        """
        mod = mod_getter()
        k = _key(mod, criterion_over={"target": "title,abstract"})
        k2 = _key(mod, criterion_over={"target": "title,abstract"},
                  item_over={"keywords": "totally; different; terms"})
        assert k != k2

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_truncation_changes_key(self, mod_getter):
        mod = mod_getter()
        long_item = {"abstract": "A" * 9000}
        assert (_key(mod, item_over=long_item, trunc_chars=0)
                != _key(mod, item_over=long_item, trunc_chars=1500))

    @pytest.mark.parametrize("mod_getter", [get_el, get_il], ids=["el", "il"])
    def test_key_is_sha256_hex(self, mod_getter):
        mod = mod_getter()
        k = _key(mod)
        assert len(k) == 64
        assert all(c in "0123456789abcdef" for c in k)

    def test_el_and_il_keys_differ(self):
        """The stages bake in their own PROMPT_VERSION, so an identical
        criterion and item must not collide across stages."""
        assert _key(get_el()) != _key(get_il())


# ---------------------------------------------------------------------------
# Stability across processes
# ---------------------------------------------------------------------------

_SUBPROCESS_SRC = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {tests!r})
    sys.path.insert(0, {root!r})
    import conftest
    mod = conftest.get_{stage}()
    crit = {crit}
    item = {item}
    print(mod._cache_key(model="gpt-4o-mini", criterion=crit, item=item,
                         trunc_chars=4000, endpoint={endpoint!r}))
    """
)


@pytest.mark.parametrize("stage", ["el", "il"])
def test_key_stable_across_processes(stage):
    """Identical inputs must give a byte-identical key in a fresh
    interpreter under a different PYTHONHASHSEED.

    Guards against dict-ordering or builtin ``hash()`` leaking into the
    serialisation: a key that varies per process silently disables the
    cache instead of failing loudly.
    """
    src = _SUBPROCESS_SRC.format(
        tests=str(Path(__file__).parent),
        root=str(PROJECT_ROOT),
        stage=stage,
        crit=repr(_criterion()),
        item=repr(_item()),
        endpoint=_ENDPOINT,
    )
    keys = []
    for seed in ("0", "1", "12345"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        proc = subprocess.run([sys.executable, "-c", src], capture_output=True,
                              text=True, env=env, cwd=str(PROJECT_ROOT))
        assert proc.returncode == 0, proc.stderr
        keys.append(proc.stdout.strip())
    assert len(set(keys)) == 1, (
        f"cache key varies across processes with PYTHONHASHSEED: {keys}. "
        f"Use a stable serialisation (sorted keys, no builtin hash())."
    )
    assert len(keys[0]) == 64
