#!/usr/bin/env python3
"""CLI entry for lilith-browser (run from project root). Delegates to core.cli."""

import sys
from pathlib import Path

# Allow "python main.py" from project root: core lives under src/
_root = Path(__file__).resolve().parent
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

if __name__ == "__main__":
    from core.cli import main

    sys.exit(main())
