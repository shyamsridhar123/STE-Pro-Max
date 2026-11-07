"""CLI entry point for `python -B -m integrations.mcp`."""
from __future__ import annotations

from .operations import main

if __name__ == "__main__":
    raise SystemExit(main())
