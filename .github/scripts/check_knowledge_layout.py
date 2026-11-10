#!/usr/bin/env python3
"""Check the knowledge layout rules that must never be forgotten (doc/KNOWLEDGE.md K-6, K-8).

Fails (exit 1) when:
  * a plans/*.md has no `## Status` heading,
  * a plans/*.md has no step or heading containing the word "Close",
  * a packages/*.yaml has no .claude/rules/packages/<name>.md symlink that resolves to a file.

Stdlib only; run from anywhere inside the repo: python3 .github/scripts/check_knowledge_layout.py
"""
import re
import subprocess
import sys
from pathlib import Path

# Work from the repo root so the relative paths match CI.
ROOT = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())

# `## Status` heading (any trailing text allowed).
STATUS_RE = re.compile(r"^##\s+Status\b", re.MULTILINE)
# A heading, numbered step or bullet that contains the word "Close" (capitalised, as in the
# plan template "Close: distil into note/design/skill ...").
CLOSE_RE = re.compile(r"^(?:#{1,6}\s+|\s*(?:\d+[.)]|[-*])\s+).*\bClose\b", re.MULTILINE)


def check_plans(errors):
    """Every plan needs a Status section and a Close step (K-6 'every plan's last step')."""
    for plan in sorted((ROOT / "plans").glob("*.md")):
        text = plan.read_text(encoding="utf-8")
        if not STATUS_RE.search(text):
            errors.append(f"{plan.relative_to(ROOT)}: no '## Status' heading")
        if not CLOSE_RE.search(text):
            errors.append(f"{plan.relative_to(ROOT)}: no step or heading containing 'Close'")


def check_package_notes(errors):
    """Every package YAML needs its note symlink under .claude/rules/packages/ (K-6 new package)."""
    for pkg in sorted((ROOT / "packages").glob("*.yaml")):
        link = ROOT / ".claude" / "rules" / "packages" / f"{pkg.stem}.md"
        # is_file() follows the symlink, so a dangling link counts as missing.
        if not link.is_symlink() or not link.is_file():
            errors.append(
                f"{pkg.relative_to(ROOT)}: missing note symlink "
                f"{link.relative_to(ROOT)} -> doc/<topic>/notes.md (doc/KNOWLEDGE.md#K-6)"
            )


def main():
    errors = []
    check_plans(errors)
    check_package_notes(errors)
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        return 1
    print("knowledge layout ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
