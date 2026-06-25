#!/usr/bin/env python3
"""
Pralph skill wrapper —便捷的 pralph 命令包装器

This wrapper provides convenient access to pralph commands from within
the phoenix-lake project, with sensible defaults and helpful shortcuts.

Usage:
    python3 .claude/skills/pralph/pralph.py <command> [args...]

Or use the installed pralph command directly after installation:
    pralph <command> [args...]
"""

import sys
import subprocess
import os
from pathlib import Path

# Path to pralph installation
PRALPH_DIR = Path("/Users/khoa.tran/plutusoft/pralph")
PRALPH_BIN = PRALPH_DIR / "bin" / "pralph"
VENV_BIN = PRALPH_DIR / ".venv" / "bin" / "python"


def run_pralph(args):
    """Run pralph with the given arguments."""
    # Check if pralph is installed
    if PRALPH_BIN.exists():
        cmd = [str(PRALPH_BIN)]
    elif VENV_BIN.exists():
        # Fall back to running via venv python
        cmd = [str(VENV_BIN), "-m", "pralph.cli"]
    else:
        print("Error: pralph not installed. Run install.sh in /Users/khoa.tran/plutusoft/pralph")
        sys.exit(1)

    cmd.extend(args)

    # Run the command
    result = subprocess.run(cmd, cwd=Path.cwd())
    sys.exit(result.returncode)


def main():
    if len(sys.argv) < 2:
        print("Usage: pralph.py <command> [args...]")
        print("\nCommands:")
        print("  plan       — Create design document")
        print("  stories    — Extract user stories")
        print("  webgen     — Discover requirements via web research")
        print("  add        — Add a single story")
        print("  ideate     — Break idea into stories")
        print("  refine     — Modify existing stories")
        print("  implement  — Implement the backlog")
        print("  justloop   — Run a prompt to completion")
        print("  compound   — Capture learnings")
        print("  query      — Query project data")
        print("  viewer     — Launch story viewer")
        sys.exit(1)

    run_pralph(sys.argv[1:])


if __name__ == "__main__":
    main()
