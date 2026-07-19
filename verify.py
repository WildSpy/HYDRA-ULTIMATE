#!/usr/bin/env python3
"""Local verification entry point used by contributors and CI."""
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    commands = [
        [sys.executable, "-m", "compileall", "-q", "main.py", "hydra"],
        [sys.executable, "-m", "pytest", "-q"],
    ]
    try:
        import ruff  # noqa: F401
    except ImportError:
        pass
    else:
        commands.insert(1, [sys.executable, "-m", "ruff", "check", "main.py", "hydra", "tests"])
    for command in commands:
        print("$", " ".join(command))
        if subprocess.run(command, check=False).returncode != 0:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
