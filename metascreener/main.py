# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .plugin_manager import discover
from .api_key_dialog import ApiKeyDialog

ENV_FILE_NAME = ".env"
ENV_KEY = "OPENAI_API_KEY"

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

def _save_env_key(env_path: Path, key: str):
    """Write/replace OPENAI_API_KEY in .env."""
    lines = []
    if env_path.exists():
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
    lines = [ln for ln in lines if not ln.strip().startswith(f"{ENV_KEY}=")]
    lines.append(f"{ENV_KEY}={key}")
    try:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass  # non-fatal

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
            _save_env_key(self.env_path, dlg.value)
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
        idx = self.nb.index("current")
        if 0 <= idx < len(self._plugins):
            notify_plugin(self._plugins[idx][0], "on_select", "on_show")

    def _on_close(self):
        # on_close is the BasePlugin contract; on_unload is what Plugin 02
        # implements to cancel its resolve/fetch worker thread. Fire both, or
        # closing the window mid-run leaves the thread alive.
        for plugin, _frame in self._plugins:
            notify_plugin(plugin, "on_close", "on_unload")
        self.destroy()
