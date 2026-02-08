# -*- coding: utf-8 -*-
"""
References-of-X — AI v1 (entry)
--------------------------------
This file stays as the entry point your Hub calls.
It simply delegates to the UI layer's `main()`.

Run:
    python references_of_x_ai_v1.py
"""


from .ui import main  # type: ignore  # noqa: F401

if __name__ == "__main__":
    main()
