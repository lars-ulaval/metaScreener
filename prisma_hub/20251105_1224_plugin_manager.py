import importlib, pkgutil, pathlib
from .plugin_api import BasePlugin

def discover(app, plugins_pkg="plugins"):
    plugins = []
    pkg = importlib.import_module(plugins_pkg)
    pkg_path = pathlib.Path(pkg.__file__).parent

    for modinfo in pkgutil.iter_modules([str(pkg_path)]):
        name = f"{plugins_pkg}.{modinfo.name}.plugin"
        try:
            mod = importlib.import_module(name)
            if hasattr(mod, "create_plugin"):
                plugin = mod.create_plugin(app)  # returns BasePlugin
                plugins.append(plugin)
        except Exception as e:
            print(f"[Hub] Failed to load {name}: {e}")
    return plugins
