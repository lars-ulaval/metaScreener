TAB_TITLE = "Citations — PRISMA AI"

from tkinter import ttk
import tkinter.messagebox as messagebox
from prisma_hub.plugin_api import PluginMeta, BasePlugin

def create_plugin(app):
    meta = PluginMeta(id="prisma_ai_v3_1", title="PRISMA Citations AI v3.1")
    return PrismaCitationsEmbedded(app, meta)

class PrismaCitationsEmbedded(BasePlugin):
    def build_tab(self, parent):
        f = ttk.Frame(parent)
        try:
            # IMPORTANT: ton fichier doit exposer une classe Frame nommée PrismaAIV3View (voir étape C)
            # from plugins.prisma_citations_ai_v3_1.original import prisma_citations_ai_v3_1 as mod
            from .original import prisma_citations_ai_v3_1 as mod
            self.view = mod.PrismaAIV3View(f)   # master=frame du hub
            self.view.pack(fill="both", expand=True)
        except Exception as e:
            msg = f"Impossible d'intégrer l'outil : {e}"
            ttk.Label(f, text=msg).pack(padx=12, pady=12, anchor="w")
        return f


