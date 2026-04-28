# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

# Importing plugin_manager is enough: it installs the sanitizer at import time.
import prisma_hub.plugin_manager  # side-effect: installs meta-path sanitizer
from prisma_hub.main import PrismaHubApp

def main():
    """Entry point for the metascreener console command."""
    PrismaHubApp().mainloop()


if __name__ == "__main__":
    main()
