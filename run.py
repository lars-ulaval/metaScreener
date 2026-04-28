# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

# Importing plugin_manager is enough: it installs the sanitizer at import time.
import metascreener.plugin_manager  # side-effect: installs meta-path sanitizer
from metascreener.main import MetaScreenerApp

def main():
    """Entry point for the metascreener console command."""
    MetaScreenerApp().mainloop()


if __name__ == "__main__":
    main()
