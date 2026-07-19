"""Validate a release tag and extract its section from CHANGELOG.md."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from hydra import __version__


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("--output", default="release-notes.md")
    args = parser.parse_args()

    version = args.tag.removeprefix("v")
    if version != __version__:
        raise SystemExit(f"tag {args.tag} does not match hydra.__version__ {__version__}")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\].*?\n(?P<body>.*?)(?=^## \[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(changelog)
    if match is None:
        raise SystemExit(f"CHANGELOG.md has no release section for {version}")
    notes = match.group("body").strip() + "\n"
    Path(args.output).write_text(notes, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
