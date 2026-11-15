#!/usr/bin/env python3
"""Check the knowledge layout rules that must never be forgotten (doc/KNOWLEDGE.md K-4, K-6, K-8).

Fails (exit 1) when:
  * a plans/*.md has neither a `## Status` heading nor a line starting `**Status:**`,
  * a plans/*.md has no Close step. Matched, case-sensitive, outside fenced code blocks:
      - a line that IS the step: optional list marker (`-`, `*`, `+`, `1.`, `1)`), optional
        status tag (`[TODO]`, `**[DONE]**` ...), optional bold, then `Close:`;
      - or a heading `#`..`######` with `Close` (optionally `Step N - Close` / `Step N – Close`).
    A sentence that merely contains the word ("- Close the valve") does not count.
  * a packages/*.yaml has no .claude/rules/packages/<name>.md symlink that resolves to a file
    (packages/ha_ci_fixtures.yaml is CI-generated and skipped).
  * a doc/<pkg>/design.md (K-4) is over 40000 chars, has no doc/<pkg>/notes.md, is not listed in
    that note's `paths:` frontmatter, or shares its ID prefix (`PG`, `AF` ...) with another design
    doc,
  * a design-ID reference does not resolve to a heading `## <ID>` .. `#### <ID>` in its design doc.
    Scanned: tracked and untracked (not ignored) .md/.yaml/.py/.jinja files except background,
    doc/sources/, doc/KNOWLEDGE.md (examples) and this script. Two forms: `doc/<pkg>/design.md#<ID>`
    and a bare `<PREFIX>-<n>[.<m>][a-z]` whose prefix a design doc defines. Lines starting
    `Retired:` in a design doc are skipped (they list gone IDs on purpose).

Warns (exit code unchanged) when a design doc has a history marker outside code fences (a date,
`pre-#n`, `since #n`, "originally", "previously", "formerly", "no longer"): K-4 keeps design docs
history-free; the warning becomes an error once the existing docs are clean.

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
# Design-doc size cap in characters (doc/KNOWLEDGE.md K-4).
DESIGN_MAX_CHARS = 40000
# A design-doc heading that carries a stable ID: `## PG-4`, `#### AF-7.1.1`, `### AF-5.3b`.
ID_HEAD_RE = re.compile(r"^#{2,4}\s+([A-Z]+-\d+(?:\.\d+)*[a-z]?)(?![\w-])", re.MULTILINE)
# Reference with path: doc/<pkg>/design.md#<ID> (a `<pkg>` placeholder never matches).
FULL_REF_RE = re.compile(r"doc/([\w-]+)/design\.md#([A-Z]+-\d+(?:\.\d+)*[a-z]?)(?![\w-])")
# History markers a current-architecture doc should not need (warning only, see docstring).
HISTORY_RE = re.compile(
    r"\b(?:20\d\d-\d\d-\d\d|pre-#\d+|since #\d+|originally|previously|formerly|no longer)\b",
    re.IGNORECASE,
)
# File types that can hold a design-ID reference.
REF_SUFFIXES = {".md", ".yaml", ".py", ".jinja"}


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


def note_paths(note):
    """Return the `paths:` list entries of a note's YAML frontmatter (stdlib only)."""
    lines = note.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    out, in_paths = [], False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if re.match(r"paths:\s*$", line):
            in_paths = True
        elif in_paths and re.match(r"\s+-\s+", line):
            out.append(line.split("-", 1)[1].strip().strip("\"'"))
        else:
            in_paths = False
    return out


def design_ids(errors):
    """Collect heading IDs per design doc; return ({pkg: ids}, {prefix: pkg})."""
    ids, prefixes = {}, {}
    for design in sorted((ROOT / "doc").glob("*/design.md")):
        pkg = design.parent.name
        found = set(ID_HEAD_RE.findall(strip_fences(design.read_text(encoding="utf-8"))))
        ids[pkg] = found
        # One prefix belongs to one design doc, so a bare ID names exactly one doc.
        for prefix in sorted({i.split("-")[0] for i in found}):
            if prefixes.get(prefix, pkg) != pkg:
                errors.append(
                    f"doc/{pkg}/design.md: ID prefix {prefix}- also used by "
                    f"doc/{prefixes[prefix]}/design.md (doc/KNOWLEDGE.md#K-4)"
                )
            prefixes.setdefault(prefix, pkg)
    return ids, prefixes


def check_design_docs(errors, warnings):
    """Each design doc: size cap, a note listing it in `paths:`, history markers warned (K-4)."""
    for design in sorted((ROOT / "doc").glob("*/design.md")):
        rel = design.relative_to(ROOT).as_posix()
        text = design.read_text(encoding="utf-8")
        if len(text) > DESIGN_MAX_CHARS:
            errors.append(f"{rel}: {len(text)} chars, cap {DESIGN_MAX_CHARS} (doc/KNOWLEDGE.md#K-4)")
        note = design.parent / "notes.md"
        if not note.is_file():
            errors.append(f"{rel}: no doc/{design.parent.name}/notes.md (doc/KNOWLEDGE.md#K-6)")
        elif rel not in note_paths(note):
            errors.append(
                f"{rel}: not listed in doc/{design.parent.name}/notes.md `paths:` "
                "(doc/KNOWLEDGE.md#K-4)"
            )
        # Warning only: the quoted marker makes the line greppable (fence stripping shifts numbers).
        for line in strip_fences(text).splitlines():
            m = HISTORY_RE.search(line)
            if m:
                warnings.append(f"{rel}: history marker '{m.group(0)}' (K-4): {line.strip()[:80]}")


def ref_files():
    """Yield (name, path) of tracked and untracked (not ignored) files that may cite a design ID."""
    out = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, text=True
    )
    for name in sorted(set(out.splitlines())):
        path = ROOT / name
        # Skip guarded history/raw material, other worktrees, the conventions file (its ID
        # examples) and this script (its patterns).
        if (
            "background" in path.name
            or name.startswith(("doc/sources/", ".claude/worktrees/"))
            or name in ("doc/KNOWLEDGE.md", ".github/scripts/check_knowledge_layout.py")
            or path.suffix not in REF_SUFFIXES
            or path.is_symlink()
            or not path.is_file()
        ):
            continue
        yield name, path


def check_design_refs(errors):
    """Every design-ID reference must name an existing heading (K-4 IDs, K-5 pointers)."""
    ids, prefixes = design_ids(errors)
    if not prefixes:
        return
    # Bare ID with a known prefix, not part of a longer token (`PG-B1`, `VIC-N3` never match).
    bare_re = re.compile(
        r"(?<![\w-])((?:%s)-\d+(?:\.\d+)*[a-z]?)(?![\w-])" % "|".join(sorted(prefixes))
    )
    for name, path in ref_files():
        is_design = name.startswith("doc/") and path.name == "design.md"
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            # A design doc's `Retired:` line names gone IDs on purpose.
            if is_design and line.startswith("Retired:"):
                continue
            for pkg, ref in FULL_REF_RE.findall(line):
                if ref not in ids.get(pkg, set()):
                    errors.append(f"{name}:{n}: doc/{pkg}/design.md#{ref} has no such heading")
            # Full references are checked above; drop them so they are not reported twice.
            for ref in bare_re.findall(FULL_REF_RE.sub("", line)):
                owner = prefixes[ref.split("-")[0]]
                if ref not in ids[owner]:
                    errors.append(f"{name}:{n}: {ref} has no heading in doc/{owner}/design.md")


def main():
    errors, warnings = [], []
    check_plans(errors)
    check_package_notes(errors)
    check_design_docs(errors, warnings)
    check_design_refs(errors)
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        return 1
    print("knowledge layout ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
