#!/usr/bin/env python3
"""CLI entry for lilith-browser (run from project root). Delegates to core.cli."""
import sys

if __name__ == "__main__":
    from core.cli import main
    sys.exit(main())
