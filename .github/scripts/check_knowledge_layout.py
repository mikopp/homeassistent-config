#!/usr/bin/env python3
"""Check the knowledge layout rules that must never be forgotten (doc/KNOWLEDGE.md K-6, K-8).

Fails (exit 1) when:
  * a plans/*.md has neither a `## Status` heading nor a line starting `**Status:**`,
  * a plans/*.md has no Close step. Matched, case-sensitive, outside fenced code blocks:
      - a line that IS the step: optional list marker (`-`, `*`, `+`, `1.`, `1)`), optional
        status tag (`[TODO]`, `**[DONE]**` ...), optional bold, then `Close:`;
      - or a heading `#`..`######` with `Close` (optionally `Step N - Close` / `Step N – Close`).
    A sentence that merely contains the word ("- Close the valve") does not count.
  * a packages/*.yaml has no .claude/rules/packages/<name>.md symlink that resolves to a file
    (packages/ha_ci_fixtures.yaml is CI-generated and skipped).

Stdlib only; run from anywhere inside the repo: python3 .github/scripts/check_knowledge_layout.py
"""
import re
import subprocess
import sys
from pathlib import Path

# Work from the repo root so the relative paths match CI.
ROOT = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())

# Status: a `## Status` heading (any trailing text) or a line starting `**Status:**`.
STATUS_RE = re.compile(r"^(?:##\s+Status\b|\*\*Status:\*\*)", re.MULTILINE)
# Close step as its own line: [list marker] [status tag] [bold] `Close:` (case-sensitive).
CLOSE_STEP_RE = re.compile(
    r"^\s*(?:(?:[-*+]|\d+[.)])\s+)?(?:\*{0,2}\[[A-Z_]+\]\*{0,2}\s*)?\*{0,2}Close(?::|\*\*:)",
    re.MULTILINE,
)
# Close as a heading, optionally "Step N - Close" (hyphen or en dash).
CLOSE_HEAD_RE = re.compile(r"^#{1,6}\s+(?:Step\s+\d+\s*[-\u2013]\s*)?Close\b", re.MULTILINE)
# Package YAML files that are generated in CI and need no note.
SKIP_PACKAGES = {"ha_ci_fixtures"}


def strip_fences(text):
    """Drop fenced code blocks (``` or ~~~) so examples inside them never satisfy a check."""
    out, fence = [], None
    for line in text.splitlines():
        m = re.match(r"\s*(```|~~~)", line)
        if m and fence is None:
            fence = m.group(1)
        elif m and m.group(1) == fence:
            fence = None
        elif fence is None:
            out.append(line)
    return "\n".join(out)


def check_plans(errors):
    """Every plan needs a Status section and a Close step (K-6 'every plan's last step')."""
    for plan in sorted((ROOT / "plans").glob("*.md")):
        text = strip_fences(plan.read_text(encoding="utf-8"))
        if not STATUS_RE.search(text):
            errors.append(f"{plan.relative_to(ROOT)}: no '## Status' heading or '**Status:**' line")
        if not (CLOSE_STEP_RE.search(text) or CLOSE_HEAD_RE.search(text)):
            errors.append(f"{plan.relative_to(ROOT)}: no 'Close:' step or 'Close' heading")


def check_package_notes(errors):
    """Every package YAML needs its note symlink under .claude/rules/packages/ (K-6 new package)."""
    for pkg in sorted((ROOT / "packages").glob("*.yaml")):
        # CI-generated fixtures package: no note by design.
        if pkg.stem in SKIP_PACKAGES:
            continue
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
