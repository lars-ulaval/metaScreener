from tkinter import ttk
from prisma_hub.plugin_api import PluginMeta, BasePlugin

def create_plugin(app):
    return HelloPlugin(app, PluginMeta(id="hello", title="Hello World"))

class HelloPlugin(BasePlugin):
    def build_tab(self, parent):
        f = ttk.Frame(parent, padding=12)
        ttk.Label(f, text="This is a sample plugin tab.").pack(anchor="w")
        return f


