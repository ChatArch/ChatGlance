#!/usr/bin/env python3
"""Compatibility entrypoint; collection lives in the published ChatGlance package."""
from chatglance.codex_collector import main

if __name__ == "__main__":
    raise SystemExit(main())
