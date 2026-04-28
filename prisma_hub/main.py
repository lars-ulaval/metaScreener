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

class PrismaHubApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PRISMA Hub")
        self.geometry("1200x820")
        self.minsize(1020, 720)

        # Project root & .env path
        self.project_root = Path(__file__).resolve().parents[1]  # .../prisma-hub
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
        from prisma_hub.plugin_manager import discover
    
        def _maybe(obj, *names, default=None):
            for n in names:
                if hasattr(obj, n):
                    return getattr(obj, n)
            return default
    
        def _title_from(*candidates):
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
    
        app = self
        meta = _maybe(self, "meta", default=None)  # pass if your app exposes .meta
    
        for plugin_mod in discover(self):
            frame = None
            tab_title = _title_from(plugin_mod)
    
            # 1) Preferred: module-level build_tab(nb, app=..., meta=...)
            if hasattr(plugin_mod, "build_tab"):
                try:
                    try:
                        frame = plugin_mod.build_tab(self.nb, app=app, meta=meta)
                    except TypeError:
                        # Try fewer kwargs for legacy signatures
                        try:
                            frame = plugin_mod.build_tab(self.nb, app=app)
                        except TypeError:
                            frame = plugin_mod.build_tab(self.nb)
                except Exception as e:
                    print(f"[PLUGIN] build_tab failed in {plugin_mod.__name__}: {e}")
    
            # 2) Class-based: Plugin(...) with optional (app, meta)
            if frame is None and hasattr(plugin_mod, "Plugin"):
                PluginCls = plugin_mod.Plugin
                try:
                    try:
                        inst = PluginCls(app, meta)
                    except TypeError:
                        try:
                            inst = PluginCls(app)
                        except TypeError:
                            inst = PluginCls()
                    tab_title = _title_from(inst, plugin_mod, PluginCls)
                    frame = inst.build_tab(self.nb)
                except Exception as e:
                    print(f"[PLUGIN] Plugin class failed in {plugin_mod.__name__}: {e}")
    
            # 3) Factory: make_plugin(app, meta) → instance with build_tab(nb)
            if frame is None and hasattr(plugin_mod, "make_plugin"):
                try:
                    try:
                        inst = plugin_mod.make_plugin(app, meta)
                    except TypeError:
                        try:
                            inst = plugin_mod.make_plugin(app)
                        except TypeError:
                            inst = plugin_mod.make_plugin()
                    tab_title = _title_from(inst, plugin_mod)
                    frame = inst.build_tab(self.nb)
                except Exception as e:
                    print(f"[PLUGIN] make_plugin failed in {plugin_mod.__name__}: {e}")
    
            # 4) Fallback: first class with build_tab(self, nb)
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
                        try:
                            inst = obj(app, meta)
                        except TypeError:
                            try:
                                inst = obj(app)
                            except TypeError:
                                inst = obj()
                        tab_title = _title_from(inst, plugin_mod, obj)
                        frame = inst.build_tab(self.nb)
                        break
                    except Exception as e:
                        print(f"[PLUGIN] Fallback {name} failed in {plugin_mod.__name__}: {e}")

            if frame is None:
                print(f"[PLUGIN] Skipping {plugin_mod.__name__} (no usable entrypoint).")
                continue
    
            self.nb.add(frame, text=tab_title)

    def _on_tab_changed(self, _evt):
        idx = self.nb.index("current")
        if 0 <= idx < len(self._plugins):
            self._plugins[idx][0].on_select()

    def _on_close(self):
        for plugin, _frame in self._plugins:
            try:
                plugin.on_close()
            except Exception:
                pass
        self.destroy()
