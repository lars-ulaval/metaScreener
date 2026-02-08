# -*- coding: utf-8 -*-
"""
Created on Tue Sep  9 11:21:01 2025

@author: alere
"""

from tkinter import ttk
# Screen A â€“ package entry point
from prisma_hub.plugin_api import PluginMeta, BasePlugin
from .ScreenAPlugin import ScreenAPlugin as _ScreenA

PLUGIN_ID = "screen_a"
PLUGIN_TITLE = "Screen A (auto inclusion/exclusion)"

def create_plugin(app):
    # Hub calls this to instantiate your plugin
    return _ScreenA(app, PluginMeta(id=PLUGIN_ID, title=PLUGIN_TITLE))

