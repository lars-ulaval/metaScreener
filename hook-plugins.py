# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules("plugins")