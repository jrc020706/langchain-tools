#!/usr/bin/env python3
"""Backward-compatible entry point for the FastMCP HTTP server."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    server = Path(__file__).parent / "fastmcp" / "server.py"
    runpy.run_path(str(server), run_name="__main__")
