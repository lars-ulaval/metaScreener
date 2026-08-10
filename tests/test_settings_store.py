
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_settings_store.py — F-116: LLM settings that survive a launch.

The gap
-------
No LLM setting persisted between launches except the API key, and the
model had to be set in up to four unreconciled widgets fed by three
prefill sources plus one hardcoded literal. A local-model user retyped
the model name every launch, for ever; accidental mixed-model pipelines
were the default rather than an edge case, and nothing detected or
recorded the disagreement.

Why not ``.env``
----------------
Because it does not work in the shipped artefact, in either direction,
and its write **fails silently** — established rather than assumed:

* the PyInstaller spec is **onefile** (``EXE(pyz, a.scripts, a.binaries,
  a.datas, …)`` with no ``COLLECT``), so at runtime the bundle is
  unpacked to a temporary directory named by ``sys._MEIPASS``;
* ``metascreener/main.py`` computes ``project_root =
  Path(__file__).resolve().parents[1]``, which under onefile *is* that
  temporary directory. ``main.py`` is not frozen-aware, unlike
  ``metascreener/plugin_manager.py``, which reads ``sys._MEIPASS``;
* ``.env`` is not in the spec's ``datas``, so the read finds nothing;
* the write succeeds into the temporary directory, which PyInstaller
  deletes on exit. ``_save_env_key`` reports ``ok=True`` and the key is
  gone next launch.

That last one is **F-139's own failure mode — a persist indistinguishable
from one that worked — reintroduced by packaging**, and invisible to
F-139's fix, which verifies that the write succeeded rather than that the
location survives.

So the store lives beside the user's other application data (D2), and is
addressed from the environment rather than from ``__file__``.

Where the safe-write rules come from
------------------------------------
``metascreener/main.py::_save_env_key``'s docstring, which is F-139's
write-up and lists three properties that were each a regression in the
first version of that fix — *symlinks are followed*, *permissions are
carried over*, *the temporary name is unique*. They are re-asserted here
rather than assumed to generalise, because this is a second writer with
the same shape, and F-139's review found its fix reintroducing its own
defect class.

One rule is stricter here: this file holds an API key, so it is created
0o600 rather than inheriting the umask.
"""
import errno
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT


def _settings():
    """Load by path, the way the app-level tests do — the module must not
    require tkinter, so it needs no ``importorskip``."""
    name = "_settings_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, str(PROJECT_ROOT / "plugins" / "_common" / "settings.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


S = _settings()


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the store at a temporary directory via the environment, which
    is also how the frozen build will address it."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return S


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

class TestWhereItLives:

    def test_the_path_does_not_depend_on_the_source_tree(self, store):
        """The whole point. A path derived from ``__file__`` lands inside
        PyInstaller's temporary extraction directory and is deleted on
        exit."""
        src = str(PROJECT_ROOT).lower()
        assert src not in str(store.settings_path()).lower()

    def test_windows_uses_appdata(self, tmp_path, monkeypatch):
        """Both branches are driven on one platform, so neither is only
        ever exercised on the maintainer's machine."""
        monkeypatch.setattr(S, "_is_windows", lambda: True)
        monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
        assert (tmp_path / "roaming") in S.settings_dir().parents

    def test_elsewhere_uses_xdg_config_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(S, "_is_windows", lambda: False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        assert (tmp_path / "cfg") in S.settings_dir().parents

    def test_the_directory_is_named_for_the_application(self, store):
        assert store.settings_dir().name == "metaScreener"


# ---------------------------------------------------------------------------
# Absent is not unreadable — F-139's first rule
# ---------------------------------------------------------------------------

class TestAbsentIsNotUnreadable:

    def test_a_missing_file_reads_as_defaults(self, store):
        assert not store.settings_path().exists()
        s = store.load_settings()
        assert s == store.defaults()

    def test_an_unreadable_file_raises_rather_than_defaulting(self, store):
        """Silently defaulting would discard a user's configuration and
        then overwrite it on the next save — F-139's harm shape."""
        store.settings_path().parent.mkdir(parents=True, exist_ok=True)
        store.settings_path().write_text("{not json", encoding="utf-8")
        with pytest.raises(store.SettingsUnreadableError):
            store.load_settings()

    def test_the_error_is_a_value_error(self, store):
        """So callers that already catch broadly keep working — the
        precedent is ``InputErrorsUnreadableError`` (F-68)."""
        assert issubclass(store.SettingsUnreadableError, ValueError)

    def test_an_unreadable_file_is_never_overwritten_by_a_save(self, store):
        store.settings_path().parent.mkdir(parents=True, exist_ok=True)
        store.settings_path().write_text("{not json", encoding="utf-8")
        with pytest.raises(store.SettingsUnreadableError):
            store.update_settings(provider="openai")
        assert store.settings_path().read_text(encoding="utf-8") == "{not json"


# ---------------------------------------------------------------------------
# The write — F-139's three regressions, re-asserted
# ---------------------------------------------------------------------------

class TestTheWriteIsSafe:

    def test_a_round_trip_preserves_every_value(self, store):
        store.save_settings({**store.defaults(), "provider": "local",
                             "endpoint": "http://localhost:11434/v1",
                             "model": "qwen2.5:7b"})
        s = store.load_settings()
        assert s["provider"] == "local"
        assert s["endpoint"] == "http://localhost:11434/v1"
        assert s["model"] == "qwen2.5:7b"

    def test_unrelated_keys_survive_a_partial_update(self, store):
        """A settings file is user-authored the moment a user edits it."""
        store.save_settings({**store.defaults(), "model": "keep-me"})
        raw = json.loads(store.settings_path().read_text(encoding="utf-8"))
        raw["hand_added"] = "by the user"
        store.settings_path().write_text(json.dumps(raw), encoding="utf-8")

        store.update_settings(provider="openai")
        after = json.loads(store.settings_path().read_text(encoding="utf-8"))
        assert after["hand_added"] == "by the user"
        assert after["model"] == "keep-me"
        assert after["provider"] == "openai"

    def test_no_temporary_file_is_left_behind(self, store):
        store.update_settings(provider="local")
        leftovers = [p.name for p in store.settings_dir().iterdir()
                     if p.name != store.settings_path().name]
        assert leftovers == []

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
    def test_the_file_holding_a_key_is_not_world_readable(self, store):
        store.update_settings(api_key="sk-secret")
        mode = stat.S_IMODE(store.settings_path().stat().st_mode)
        assert not mode & stat.S_IRGRP
        assert not mode & stat.S_IROTH

    @pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt",
                        reason="symlink creation needs privileges on Windows")
    def test_a_symlinked_settings_file_is_followed_not_replaced(self, store):
        """F-139's own review found the first fix replacing the *link* with
        a regular file, so a settings file symlinked to a shared location
        silently stopped being updated while the save reported success.
        That is this function's defect class reintroduced by its own fix,
        and it must not happen twice."""
        real = store.settings_dir().parent / "real_settings.json"
        store.settings_dir().mkdir(parents=True, exist_ok=True)
        real.write_text(json.dumps(store.defaults()), encoding="utf-8")
        store.settings_path().symlink_to(real)

        store.update_settings(model="through-the-link")

        assert store.settings_path().is_symlink(), "the link was replaced"
        assert json.loads(real.read_text(encoding="utf-8"))["model"] == \
            "through-the-link"


# ---------------------------------------------------------------------------
# App-level setting with per-stage override
# ---------------------------------------------------------------------------

class TestResolution:

    def test_a_stage_inherits_the_app_level_model(self, store):
        store.update_settings(model="app-wide")
        assert store.effective_model(store.load_settings(), "EL") == "app-wide"

    def test_a_stage_override_wins(self, store):
        store.update_settings(model="app-wide")
        store.set_stage_override("IL", model="il-only")
        s = store.load_settings()
        assert store.effective_model(s, "EL") == "app-wide"
        assert store.effective_model(s, "IL") == "il-only"

    def test_clearing_an_override_falls_back(self, store):
        store.update_settings(model="app-wide")
        store.set_stage_override("IL", model="il-only")
        store.set_stage_override("IL", model="")
        assert store.effective_model(store.load_settings(), "IL") == "app-wide"

    def test_a_whitespace_override_is_not_an_override(self, store):
        """F-93's shape: a whitespace-only field is truthy and reaches the
        engine as an empty model, which it takes as 'no model' and skips
        silently."""
        store.update_settings(model="app-wide")
        store.set_stage_override("EL", model="   ")
        assert store.effective_model(store.load_settings(), "EL") == "app-wide"


# ---------------------------------------------------------------------------
# Mixed models — the half of F-116 that is not persistence
# ---------------------------------------------------------------------------

class TestMixedModelsAreDetected:
    """The row says accidental mixed-model pipelines are the default rather
    than an edge case, and that *nothing detects or records the
    disagreement* — which is F-88 again, since no artefact would show it."""

    def test_one_model_everywhere_is_not_mixed(self, store):
        store.update_settings(model="one")
        assert store.mixed_models(store.load_settings(), ("EL", "IL")) == ()

    def test_a_divergent_override_is_reported(self, store):
        store.update_settings(model="one")
        store.set_stage_override("IL", model="two")
        assert store.mixed_models(store.load_settings(), ("EL", "IL")) == \
            ("one", "two")

    def test_the_report_is_sorted_and_deduplicated(self, store):
        store.update_settings(model="b")
        store.set_stage_override("EL", model="a")
        store.set_stage_override("IL", model="a")
        assert store.mixed_models(
            store.load_settings(), ("EL", "IL", "harmoniser")) == ("a", "b")


# ---------------------------------------------------------------------------
# Schema tolerance — old files must still load
# ---------------------------------------------------------------------------

class TestOldFilesStillLoad:
    """F-68/F-70's standing rule in this project: an artefact written by an
    earlier version is on disk and in users' hands."""

    def test_a_file_with_unknown_keys_is_preserved_and_readable(self, store):
        store.settings_dir().mkdir(parents=True, exist_ok=True)
        store.settings_path().write_text(
            json.dumps({"schema": 999, "from_the_future": True}),
            encoding="utf-8")
        s = store.load_settings()
        assert s["from_the_future"] is True
        assert s["model"] == store.defaults()["model"], "missing keys default"

    def test_a_file_that_is_not_an_object_is_unreadable_not_empty(self, store):
        store.settings_dir().mkdir(parents=True, exist_ok=True)
        store.settings_path().write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(store.SettingsUnreadableError):
            store.load_settings()
