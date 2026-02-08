import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .plugin_manager import discover
from .api_key_dialog import ApiKeyDialog

ENV_FILE_NAME = ".env"
ENV_KEY = "OPENAI_API_KEY"

def _load_env_file(env_path: Path):
    """Very small .env reader: loads KEY=VALUE lines into os.environ."""
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
    # remove old line(s)
    lines = [ln for ln in lines if not ln.strip().startswith(f"{ENV_KEY}=")]
    lines.append(f'{ENV_KEY}={key}')
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

        # Load existing .env if present (so we can skip the dialog next time)
        self.project_root = Path(__file__).resolve().parents[1]  # .../prisma-hub
        self.env_path = self.project_root / ENV_FILE_NAME
        _load_env_file(self.env_path)

        # Ask for API key up-front if missing; exit if user cancels/closes
        if not self._ensure_api_key():
            # Close the app immediately
            self.after(0, self.destroy)
            return

        # Main UI
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self._plugins = []
        self._load_plugins()

        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _ensure_api_key(self) -> bool:
        if os.environ.get(ENV_KEY):
            return True
        dlg = ApiKeyDialog(self, existing_key="", remember_default=True)
        self.wait_window(dlg)
        if not dlg.value:
            return False  # user cancelled
        # Set for this process
        os.environ[ENV_KEY] = dlg.value
        # Persist to .env if requested
        if dlg.remember_var.get():
            _save_env_key(self.env_path, dlg.value)
        return True

    def _load_plugins(self):
        for plugin in discover(self):
            frame = plugin.build_tab(self.nb)
            self.nb.add(frame, text=plugin.meta.title)
            self._plugins.append((plugin, frame))

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
