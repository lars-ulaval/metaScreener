# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

import os
import stat
import uuid
from pathlib import Path
from typing import List, NamedTuple
import tkinter as tk
from tkinter import ttk, messagebox

from .plugin_manager import discover
from .api_key_dialog import ApiKeyDialog

ENV_FILE_NAME = ".env"
ENV_KEY = "OPENAI_API_KEY"


class EnvSaveResult(NamedTuple):
    """Whether the key reached ``.env``, and what to tell the user if not.

    F-139. ``_save_env_key`` used to return ``None`` and swallow every
    failure, so a persist that did nothing was indistinguishable from one
    that worked — the user was silently re-prompted on the next launch
    with no explanation. A caller cannot report what it is not told.
    """
    ok: bool
    message: str

def _load_env_file(env_path: Path):
    """Tiny .env reader: loads KEY=VALUE lines into os.environ (for prefill)."""
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass  # non-fatal

def _save_env_key(env_path: Path, key: str) -> EnvSaveResult:
    """Write/replace OPENAI_API_KEY in .env, preserving everything else.

    F-139. This used to open with ``lines = []``, overwrite that with the
    file's contents inside a ``try``, and fall back to ``lines = []`` when
    the read raised — then write unconditionally. ``Path.write_text``
    truncates at open, so a ``.env`` that existed but could not be decoded
    was not preserved, it was **destroyed** and replaced by
    ``OPENAI_API_KEY=<new>`` alone. Reproduced: a file holding
    ``OPENAI_BASE_URL``, ``SCREENA_EL_MODEL`` and ``OPENAI_API_KEY`` became
    one line.

    The ``except`` that made the read non-fatal was precisely what made the
    write destructive; the two were written as one defensive gesture, and
    nothing between them distinguished *the file was empty* from *the read
    failed*. What is lost is the user's **only** persisted configuration —
    there is no settings file, no registry use and no config parser
    anywhere (F-116) — and ``OPENAI_BASE_URL``, which wave 9 puts into the
    LLM cache key, is in the blast radius.

    Three rules now, and they are three different failures:

    **Absent is not unreadable.** A missing ``.env`` is created; a ``.env``
    that raises on read is refused, with the file left exactly as it was.
    The user can fix the encoding; they cannot un-destroy the file.

    **The write is atomic.** Written to a sibling temporary and moved into
    place with ``os.replace``, which is atomic on Windows and POSIX alike.
    A truncating write that fails part-way — a full disk is the realistic
    trigger — is F-139's own harm shape reached through a different door,
    so guarding only the read would have left it open. The temporary is
    removed if the move fails, because it holds the user's key and a
    stray copy of a secret in the project root is its own defect.

    Three properties of that write are load-bearing, and each was a
    regression in the first version of this fix, found in review:

    * **Symlinks are followed.** Renaming onto the link path would replace
      the *link* with a regular file, so a ``.env`` symlinked to a shared
      location would silently stop being updated while the function
      reported success — this function's own defect class, reintroduced by
      its own fix.
    * **Permissions are carried over.** The plain write truncated the
      original inode, so a ``chmod 600`` survived it. A fresh temporary is
      born at ``0o666 & ~umask``, so without this the first save after
      ``chmod 600`` would quietly make a file holding an API key
      world-readable.
    * **The temporary name is unique.** A constant one lets two instances
      overwrite each other's, so one could move the *other's* key into
      place while reporting its own save as failed. The app prompts on
      every launch, so two windows at once is ordinary. This does not make
      the read-modify-write atomic — the last writer still wins on the file
      as a whole, which needs a lock and is wave 11's — but each save now
      reports what it actually wrote.

    **Silence is not success.** The result says which happened. Refusing
    to write and then saying nothing is the same silence one layer up.

    Deliberately *not* fixed here, because wave 11 owns ``.env`` handling
    and this wave's remit is the data-loss defect only: the filter below
    matches the literal prefix while ``_load_env_file`` splits on the first
    ``=`` and strips, so ``OPENAI_API_KEY = x`` and ``export
    OPENAI_API_KEY=x`` survive it and win on reload (first occurrence
    wins); a UTF-8 BOM hides the line from the filter the same way; and
    the value is written unescaped, so an interior newline splits it.
    """
    lines: List[str] = []
    if env_path.exists():
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            return EnvSaveResult(
                False,
                f"Could not read {env_path}, so it was left unchanged and "
                f"the key was not saved: {e.__class__.__name__}: {e}\n\n"
                f"The file exists but could not be decoded as UTF-8 or "
                f"could not be opened. Nothing was overwritten, and your "
                f"other settings in it are intact.\n\n"
                f"Fix or remove the file, then restart metaScreener. The "
                f"key you just entered is active for this session either "
                f"way.",
            )

    lines = [ln for ln in lines if not ln.strip().startswith(f"{ENV_KEY}=")]
    lines.append(f"{ENV_KEY}={key}")

    # Follow a symlink, the way the plain write this replaced did. Renaming
    # onto the link path would replace the LINK with a regular file, so a
    # user who keeps `.env` symlinked to a shared location would silently
    # stop updating the file they manage — and the stale target would keep
    # serving an old key. Reporting that as a success is the defect class
    # this function exists to fix, so it must not be reintroduced by the fix.
    target = Path(os.path.realpath(env_path))

    # Unique per call. A constant `.env.tmp` lets two instances overwrite
    # each other's temporary, so one could move the OTHER's key into place
    # and still report its own save as failed. The app prompts for the key
    # on every launch, so two windows at once is ordinary rather than
    # exotic. This does not make a read-modify-write atomic — the last
    # writer still wins on the file as a whole — but it stops the two saves
    # from interleaving, so each reports what it actually wrote.
    tmp_path = target.with_name(
        f"{target.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    )
    try:
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Carry the existing file's permissions onto the replacement. The
        # plain write truncated the original inode, so a `chmod 600` on a
        # file holding an API key survived it; a fresh temporary is created
        # at `0o666 & ~umask` and `os.replace` would carry that mode in,
        # quietly widening the file. No-op on Windows, which does not use
        # these bits.
        try:
            if target.exists():
                os.chmod(tmp_path, stat.S_IMODE(target.stat().st_mode))
        except Exception:
            pass
        os.replace(tmp_path, target)
    except Exception as e:
        try:
            tmp_path.unlink()
        except Exception:
            pass
        # Name the path that actually failed. `target` and `env_path` differ
        # when `.env` is a symlink, and sending the user to inspect the
        # wrong file is its own small defect.
        return EnvSaveResult(
            False,
            f"Could not write {target}, so it was left unchanged and the "
            f"key was not saved: {e.__class__.__name__}: {e}",
        )

    return EnvSaveResult(True, f"Saved {ENV_KEY} to {target}.")

# ---------------------------------------------------------------------------
# Plugin entry-point resolution and lifecycle dispatch
#
# These are module-level functions rather than methods so they can be unit
# tested without constructing a Tk root (metascreener/main.py was at 0%
# coverage). MetaScreenerApp delegates to them.
# ---------------------------------------------------------------------------

def _title_from(*candidates) -> str:
    """First usable tab title among the candidates, else "Plugin"."""
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
        if hasattr(c, "TAB_TITLE"):
            t = getattr(c, "TAB_TITLE")
            if isinstance(t, str) and t.strip():
                return t.strip()
        if hasattr(c, "tab_title") and callable(getattr(c, "tab_title")):
            try:
                t = c.tab_title()
                if isinstance(t, str) and t.strip():
                    return t.strip()
            except Exception:
                pass
    return "Plugin"


def _call_with_degrading_args(factory, app, meta):
    """Call factory(app, meta), then (app), then (), taking the first that fits."""
    try:
        return factory(app, meta)
    except TypeError:
        try:
            return factory(app)
        except TypeError:
            return factory()


def resolve_plugin_entrypoint(plugin_mod, parent, app=None, meta=None):
    """Build a plugin's tab, returning (instance, frame, tab_title).

    Four strategies, tried in order: a module-level build_tab, a class named
    Plugin, a factory named make_plugin, and finally a scan for the first
    class exposing build_tab. `instance` is None only for the module-level
    build_tab strategy, which has no object to hang a lifecycle on; `frame`
    is None if every strategy failed.

    Returning the instance is what makes the BasePlugin lifecycle work at
    all: MetaScreenerApp used to discard it, so self._plugins stayed empty
    and on_select/on_close were never called (F-18).
    """
    tab_title = _title_from(plugin_mod)
    inst = None
    frame = None

    # 1) module-level build_tab(nb, app=..., meta=...)
    if hasattr(plugin_mod, "build_tab"):
        try:
            try:
                frame = plugin_mod.build_tab(parent, app=app, meta=meta)
            except TypeError:
                try:
                    frame = plugin_mod.build_tab(parent, app=app)
                except TypeError:
                    frame = plugin_mod.build_tab(parent)
        except Exception as e:
            print(f"[PLUGIN] build_tab failed in {plugin_mod.__name__}: {e}")

    # 2) class named Plugin
    if frame is None and hasattr(plugin_mod, "Plugin"):
        PluginCls = plugin_mod.Plugin
        try:
            inst = _call_with_degrading_args(PluginCls, app, meta)
            tab_title = _title_from(inst, plugin_mod, PluginCls)
            frame = inst.build_tab(parent)
        except Exception as e:
            inst = None
            print(f"[PLUGIN] Plugin class failed in {plugin_mod.__name__}: {e}")

    # 3) factory named make_plugin
    if frame is None and hasattr(plugin_mod, "make_plugin"):
        try:
            inst = _call_with_degrading_args(plugin_mod.make_plugin, app, meta)
            tab_title = _title_from(inst, plugin_mod)
            frame = inst.build_tab(parent)
        except Exception as e:
            inst = None
            print(f"[PLUGIN] make_plugin failed in {plugin_mod.__name__}: {e}")

    # 4) fallback: first class exposing build_tab
    if frame is None:
        for name, obj in vars(plugin_mod).items():
            if not isinstance(obj, type):
                continue
            if name.lower() == "baseplugin":
                continue
            if getattr(obj, "IS_ABSTRACT", False):
                continue
            if not hasattr(obj, "build_tab"):
                continue
            try:
                inst = _call_with_degrading_args(obj, app, meta)
                tab_title = _title_from(inst, plugin_mod, obj)
                frame = inst.build_tab(parent)
                break
            except Exception as e:
                inst = None
                print(f"[PLUGIN] Fallback {name} failed in {plugin_mod.__name__}: {e}")

    return inst, frame, tab_title


def notify_plugin(plugin, *hook_names) -> bool:
    """Call every hook in hook_names that `plugin` defines. Never raises.

    Returns True if at least one hook ran. Plugins declare different
    lifecycle vocabularies - the BasePlugin contract has on_close, while
    Plugin 02 implements on_unload for cooperative worker cancellation - so
    callers pass every name that means the same thing.
    """
    if plugin is None:
        return False
    ran = False
    for name in hook_names:
        hook = getattr(plugin, name, None)
        if not callable(hook):
            continue
        try:
            hook()
            ran = True
        except Exception as e:
            print(f"[PLUGIN] {name}() failed in {type(plugin).__name__}: {e}")
    return ran


class MetaScreenerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("metaScreener")
        self.geometry("1200x820")
        self.minsize(1020, 720)

        # Project root & .env path
        self.project_root = Path(__file__).resolve().parents[1]  # .../metaScreener
        self.env_path = self.project_root / ENV_FILE_NAME

        # Load .env only to PREFILL (we will still prompt every time)
        _load_env_file(self.env_path)

        # Always prompt; exit if user cancels
        if not self._prompt_api_key_always():
            self.after(0, self.destroy)
            return

        # Main UI
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self._plugins = []
        self._load_plugins()

        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _prompt_api_key_always(self) -> bool:
        """Show the API key dialog on every launch, regardless of existing values."""
        # Prefill with any existing value (env or .env) for convenience
        existing = os.environ.get(ENV_KEY, "")
        dlg = ApiKeyDialog(self, existing_key=existing, remember_default=True)
        self.wait_window(dlg)
        if not dlg.value:
            return False  # user cancelled

        # Use what the user entered for this process
        os.environ[ENV_KEY] = dlg.value

        # Persist to .env only if they checked 'Remember'
        if dlg.remember_var.get():
            # F-139: a persist that did nothing used to be indistinguishable
            # from one that worked. The run continues either way — the key is
            # already in os.environ for this process, so failing to persist
            # costs a re-type next launch and nothing more — but the user is
            # told, because the two states differ next launch and only one of
            # them is their fault to fix.
            #
            # Direct messagebox rather than an `after` marshal: this runs on
            # the main thread during __init__. F-112/F-137's marshalling
            # applies to the worker threads, not here.
            result = _save_env_key(self.env_path, dlg.value)
            if not result.ok:
                messagebox.showwarning("Could not save the API key",
                                       result.message, parent=self)
        return True

    def _load_plugins(self):
        from metascreener.plugin_manager import discover

        meta = getattr(self, "meta", None)  # pass if the app exposes .meta

        for plugin_mod in discover(self):
            inst, frame, tab_title = resolve_plugin_entrypoint(
                plugin_mod, self.nb, app=self, meta=meta
            )
            if frame is None:
                print(f"[PLUGIN] Skipping {plugin_mod.__name__} (no usable entrypoint).")
                continue

            # Keep _plugins index-aligned with notebook tabs, including the
            # module-level build_tab case where there is no instance.
            self._plugins.append((inst, frame))
            self.nb.add(frame, text=tab_title)

    def _on_tab_changed(self, _evt):
        # on_select only. on_show/on_hide are a separate, undocumented pair
        # that is not part of the BasePlugin contract in plugin_api.py, and
        # firing on_show without a matching on_hide would be half a feature.
        # See F-59 for why plugin 02's implementation of that pair could not
        # work anyway.
        idx = self.nb.index("current")
        if 0 <= idx < len(self._plugins):
            notify_plugin(self._plugins[idx][0], "on_select")

    def _on_close(self):
        # on_close is the BasePlugin contract; on_unload is what Plugin 02
        # implements to cancel its resolve/fetch worker thread. Fire both, or
        # closing the window mid-run leaves the thread alive.
        for plugin, _frame in self._plugins:
            notify_plugin(plugin, "on_close", "on_unload")
        self.destroy()
