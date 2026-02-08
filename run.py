# Importing plugin_manager is enough: it installs the sanitizer at import time.
import prisma_hub.plugin_manager  # side-effect: installs meta-path sanitizer
from prisma_hub.main import PrismaHubApp

if __name__ == "__main__":
    PrismaHubApp().mainloop()
