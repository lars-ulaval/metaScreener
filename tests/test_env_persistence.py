
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_env_persistence.py — F-139: a ``.env`` that cannot be read must not
be replaced by one line.

The defect this pins
--------------------
``_save_env_key`` opened with ``lines = []``, overwrote that with the
file's contents inside a ``try``, and fell back to ``lines = []`` when the
read raised. The write that followed was **unconditional**, and
``Path.write_text`` truncates at open — so a ``.env`` that existed but
could not be decoded was not preserved, it was destroyed, and replaced by
``OPENAI_API_KEY=<new>`` alone.

The ``except`` that made the read non-fatal is precisely what made the
write destructive: the two were written as one defensive gesture, and
nothing between them distinguished "the file was empty" from "the read
failed".

What is lost is the user's **only** persisted configuration — there is no
settings file, no registry use and no config parser anywhere (F-116) — and
``OPENAI_BASE_URL``, the variable the whole documented local-provider
workflow depends on and which wave 9 puts into the cache key, is in the
blast radius.

``test_unreadable_env_is_not_destroyed`` is the bug. The reachable trigger
is a ``.env`` saved by an editor as cp1252 or UTF-16, which
``_load_env_file`` swallows identically — so the user first sees a ``.env``
that silently loads as empty, and then loses it entirely on the next Save.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT


def _main_module():
    """Import ``metascreener/main.py`` under conftest's tkinter stubs.

    Same loader as ``tests/test_plugin_lifecycle.py``: the module imports
    tkinter at module scope (conftest has already replaced it with a
    MagicMock) and uses relative imports, which need the package stub to
    carry a ``__path__``.
    """
    ms = sys.modules.get("metascreener")
    if ms is None:
        ms = types.ModuleType("metascreener")
        sys.modules["metascreener"] = ms
    if not hasattr(ms, "__path__"):
        ms.__path__ = [str(PROJECT_ROOT / "metascreener")]
    spec = importlib.util.spec_from_file_location(
        "metascreener.main", str(PROJECT_ROOT / "metascreener" / "main.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["metascreener.main"] = mod
    spec.loader.exec_module(mod)
    return mod


# A .env holding exactly what F-139's register row says is in the blast
# radius, with a comment byte that is not valid UTF-8. 0xE9 is a 3-byte
# lead byte and the newline that follows is not a continuation byte, so
# read_text(encoding="utf-8") raises UnicodeDecodeError.
UNDECODABLE_ENV = (
    b"# caf\xe9 settings\n"
    b"OPENAI_BASE_URL=http://localhost:11434/v1\n"
    b"SCREENA_EL_MODEL=gemma3:12b\n"
    b"OPENAI_API_KEY=sk-old\n"
)


# ---------------------------------------------------------------------------
# The bug
# ---------------------------------------------------------------------------

class TestUnreadableEnvIsPreserved:

    def test_unreadable_env_is_not_destroyed(self, tmp_path):
        """**This is F-139.**

        Before the fix this file became ``OPENAI_API_KEY=sk-new`` alone —
        three settings destroyed, silently, with no message and no backup.
        """
        main = _main_module()
        env = tmp_path / ".env"
        env.write_bytes(UNDECODABLE_ENV)

        result = main._save_env_key(env, "sk-new")

        assert env.read_bytes() == UNDECODABLE_ENV, (
            "F-139: a .env that could not be decoded was overwritten. The "
            "user's only persisted configuration — OPENAI_BASE_URL among "
            "it — is gone, and nothing said so."
        )
        assert result.ok is False, (
            "Refusing to write is only half the fix. A refusal the caller "
            "cannot see is the same silence, one layer up."
        )
        assert str(env) in result.message

    def test_the_refusal_names_the_cause(self, tmp_path):
        """The message must let the user act.

        'Could not save' does not tell them their file is mis-encoded;
        without that they cannot distinguish it from a permissions problem
        and will retry the one action that used to destroy the file.
        """
        main = _main_module()
        env = tmp_path / ".env"
        env.write_bytes(UNDECODABLE_ENV)

        result = main._save_env_key(env, "sk-new")

        assert not result.ok
        lowered = result.message.lower()
        assert "utf-8" in lowered or "decode" in lowered

    def test_a_directory_in_place_of_env_is_refused(self, tmp_path):
        """``Path.exists()`` is True for a directory and ``read_text`` then
        raises, which is the same 'read failed' branch."""
        main = _main_module()
        env = tmp_path / ".env"
        env.mkdir()

        result = main._save_env_key(env, "sk-new")

        assert result.ok is False
        assert env.is_dir()


# ---------------------------------------------------------------------------
# Properties that must not regress
# ---------------------------------------------------------------------------

class TestNormalPersistence:

    def test_absent_env_is_created(self, tmp_path):
        """'Absent' and 'unreadable' are different, and only the second is
        refused. A first-time user must still get a ``.env``."""
        main = _main_module()
        env = tmp_path / ".env"

        result = main._save_env_key(env, "sk-1")

        assert result.ok is True
        assert env.read_text(encoding="utf-8").splitlines() == ["OPENAI_API_KEY=sk-1"]

    def test_other_keys_are_preserved(self, tmp_path):
        main = _main_module()
        env = tmp_path / ".env"
        env.write_text(
            "OPENAI_BASE_URL=http://localhost:11434/v1\n"
            "SCREENA_EL_MODEL=gemma3:12b\n"
            "OPENAI_API_KEY=sk-old\n",
            encoding="utf-8",
        )

        result = main._save_env_key(env, "sk-new")

        assert result.ok is True
        lines = env.read_text(encoding="utf-8").splitlines()
        assert "OPENAI_BASE_URL=http://localhost:11434/v1" in lines
        assert "SCREENA_EL_MODEL=gemma3:12b" in lines
        assert "OPENAI_API_KEY=sk-new" in lines
        assert "OPENAI_API_KEY=sk-old" not in lines

    def test_empty_env_is_not_mistaken_for_a_failed_read(self, tmp_path):
        """The distinction the old code could not draw, from the other side:
        a genuinely empty file is readable and must be written to."""
        main = _main_module()
        env = tmp_path / ".env"
        env.write_bytes(b"")

        result = main._save_env_key(env, "sk-1")

        assert result.ok is True
        assert env.read_text(encoding="utf-8").splitlines() == ["OPENAI_API_KEY=sk-1"]

    def test_a_failed_write_is_reported(self, tmp_path, monkeypatch):
        """F-139's second half: ``except Exception: pass`` around the write
        made a failed persist indistinguishable from a successful one, so
        the user was told nothing and was re-prompted on the next launch
        with no explanation."""
        main = _main_module()
        env = tmp_path / ".env"
        env.write_text("OPENAI_API_KEY=sk-old\n", encoding="utf-8")

        def _boom(*a, **kw):
            raise PermissionError("disk is read-only")

        monkeypatch.setattr(main.os, "replace", _boom)

        result = main._save_env_key(env, "sk-new")

        assert result.ok is False
        assert "read-only" in result.message or "PermissionError" in result.message

    def test_a_failed_write_leaves_the_original_intact(self, tmp_path, monkeypatch):
        """The write is atomic.

        ``Path.write_text`` truncates at open, so a write that failed
        part-way — a full disk is the realistic trigger — left the user
        with a truncated ``.env``. That is F-139's own harm shape reached
        through a different door, which is why the fix replaces the write
        rather than only guarding the read.
        """
        main = _main_module()
        env = tmp_path / ".env"
        original = "OPENAI_BASE_URL=http://localhost:11434/v1\nOPENAI_API_KEY=sk-old\n"
        env.write_text(original, encoding="utf-8")

        def _boom(*a, **kw):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(main.os, "replace", _boom)

        result = main._save_env_key(env, "sk-new")

        assert result.ok is False
        assert env.read_text(encoding="utf-8") == original

    def test_a_symlinked_env_is_followed(self, tmp_path):
        """The atomic write must not replace a symlink with a regular file.

        Regression found in review of wave 9's own F-139 fix.
        ``Path.write_text`` follows a symlink; a naive ``os.replace`` onto
        the link path replaces **the link**, so a user who keeps ``.env``
        symlinked to a shared location silently stops updating the file
        they actually manage — and the old target keeps serving a stale
        key on the next launch. Worse, it reported ``ok=True``: a success
        for a write that missed, which is the exact defect class F-139 is
        about, reintroduced by its own fix.
        """
        real = tmp_path / "real_env"
        real.write_text("OPENAI_BASE_URL=http://localhost:11434/v1\n"
                        "OPENAI_API_KEY=sk-old\n", encoding="utf-8")
        link = tmp_path / ".env"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not permitted on this machine")

        main = _main_module()
        result = main._save_env_key(link, "sk-new")

        assert result.ok is True
        assert link.is_symlink(), "the symlink was replaced by a regular file"
        text = real.read_text(encoding="utf-8")
        assert "OPENAI_API_KEY=sk-new" in text
        assert "OPENAI_BASE_URL=http://localhost:11434/v1" in text

    @pytest.mark.skipif(sys.platform == "win32",
                        reason="POSIX permission bits")
    def test_existing_permissions_are_preserved(self, tmp_path):
        """A user who runs ``chmod 600 .env`` must keep it.

        Regression found in review. The old code truncated the existing
        inode, so its mode survived; writing a fresh temporary and moving
        it in carries the *temporary's* mode — ``0666 & ~umask``, usually
        ``0644`` — so protecting the file made it world-readable on the
        next save. The file holds an API key.
        """
        import stat as _stat

        main = _main_module()
        env = tmp_path / ".env"
        env.write_text("OPENAI_API_KEY=sk-old\n", encoding="utf-8")
        env.chmod(0o600)

        assert main._save_env_key(env, "sk-new").ok is True
        assert _stat.S_IMODE(env.stat().st_mode) == 0o600

    def test_the_temporary_name_is_unique_per_process(self, tmp_path,
                                                      monkeypatch):
        """A fixed ``.env.tmp`` lets two instances corrupt each other.

        Regression found in review. The app prompts for the key on **every**
        launch, so two windows open at once is the ordinary path, not an
        exotic one. With a constant name, one instance overwrites the
        other's temporary and can move *its* key into place while
        reporting the first instance's save as failed — or, worse, report
        success having written the other instance's key.

        A unique name cannot make a read-modify-write atomic — the last
        writer still wins on the file as a whole — but it stops the two
        saves from being *interleaved*, so each reports what it actually
        wrote.
        """
        main = _main_module()
        env = tmp_path / ".env"
        env.write_text("OPENAI_API_KEY=sk-old\n", encoding="utf-8")

        seen = []
        real_replace = main.os.replace

        def _spy(src, dst):
            seen.append(Path(src).name)
            return real_replace(src, dst)

        monkeypatch.setattr(main.os, "replace", _spy)
        main._save_env_key(env, "sk-1")
        main._save_env_key(env, "sk-2")

        assert len(seen) == 2
        assert seen[0] != seen[1], (
            f"both saves used the same temporary name {seen[0]!r}; two "
            f"concurrent instances would collide on it"
        )
        for name in seen:
            assert name.startswith(".env.tmp")

    def test_no_temporary_file_is_left_behind(self, tmp_path, monkeypatch):
        """A ``.env.tmp`` holding the user's key would be a second copy of a
        secret, in a directory the user does not inspect."""
        main = _main_module()
        env = tmp_path / ".env"
        env.write_text("OPENAI_API_KEY=sk-old\n", encoding="utf-8")

        def _boom(*a, **kw):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(main.os, "replace", _boom)
        main._save_env_key(env, "sk-new")

        assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]
