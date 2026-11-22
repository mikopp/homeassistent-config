#!/usr/bin/env python3
"""Check the knowledge layout rules that must never be forgotten (doc/KNOWLEDGE.md K-1..K-9).

Fails (exit 1) when:
  * a plans/*.md has neither a `## Status` heading nor a line starting `**Status:**`,
  * a plans/*.md has no Close step. Matched, case-sensitive, outside fenced code blocks:
      - a line that IS the step: optional list marker (`-`, `*`, `+`, `1.`, `1)`), optional
        status tag (`[TODO]`, `**[DONE]**` ...), optional bold, then `Close:`;
      - or a heading `#`..`######` with `Close` (optionally `Step N - Close` / `Step N – Close`).
    A sentence that merely contains the word ("- Close the valve") does not count.
  * a packages/*.yaml has no .claude/rules/packages/<name>.md symlink that resolves to a file
    (packages/ha_ci_fixtures.yaml is CI-generated and skipped).
  * a doc/<pkg>/design.md (K-4) has no doc/<pkg>/notes.md, is not listed in that note's `paths:`
    frontmatter, or shares its ID prefix (`PG`, `AF` ...) with another design doc,
  * a knowledge file is over its hard cap in SIZE_CAPS (characters, K-1.2; symlinks resolved and
    deduplicated; `_template`, background*, doc/sources/ and the manufacturer copies under
    doc/devices/<d>/references/ skipped; skill references/*.md are capped),
  * a design-ID reference does not resolve to a heading `## <ID>` .. `#### <ID>` in its design doc.
    Scanned: tracked and untracked (not ignored) .md/.yaml/.py/.jinja files except background,
    doc/sources/, doc/KNOWLEDGE.md (examples) and this script. Two forms: `doc/<pkg>/design.md#<ID>`
    and a bare `<PREFIX>-<n>[.<m>][a-z]` whose prefix a design doc defines. Lines starting
    `Retired:` in a design doc are skipped (they list gone IDs on purpose).
  * a doc/devices/<device>/ (K-9, format in .claude/rules/devices.md; `_`-prefixed folders such as
    `_template` are skipped) lacks README.md, behaviour.md, interface.md or evidence.md (a folder
    whose only top-level .md is README.md is a minimal device: it needs `## References` with a row,
    no prefix, and may cite no `[T<n>]`), lacks a
    required heading (README `## References`; behaviour `## Control`, `## Does not work`,
    `## Open questions`; interface `## Unusable on this unit`), cites `[T<n>]` without an
    evidence*.md row or `[<REF> ...]` without a References row, has a T row without a
    YYYY-MM[-DD] date or a CONFIRMED/OBSERVED grade or a T number twice across its evidence*.md,
    has no README Identity `| Prefix | <PFX> |` row, shares its prefix with another device or a
    design doc, defines a fact ID `<PFX>-<n>` (first table cell or leading `**<PFX>-<n>**`) more
    than once, or names a plans/<file>.md that does not exist. Code spans and fences are ignored
    for tags and IDs.
  * a `(device <ID>)` anchor in doc/, packages/, tests/, plans/ or custom_templates/ names no
    defined device fact ID,
  * an .md file outside doc/devices/ carries a device evidence tag `[T<n>]` or `[<REF> p.<n>]`
    outside code (device facts are cited by anchor, K-9),
  * a .claude/skills/*/SKILL.md lacks `name:` or `description:`, or the description is over its
    SIZE_CAPS hard cap,
  * a .claude/rules/**/*.md (symlinks followed) lacks frontmatter `---` / a `paths:` list / the
    closing `---`, or has a line starting `@` (an eager import, K-1),
  * a reference part is named by no index (K-1.3; by relative path or basename):
      - a .claude/skills/<t>/**/*.md other than SKILL.md, not named in that skill's SKILL.md;
      - a doc/devices/<d>/*.md (top level; `_`-folders skipped) other than README.md,
        behaviour.md, interface.md and evidence*.md: `access-*.md` / `registers-*.md` not named
        in interface.md, any other part not named in README.md or behaviour.md; and a part whose
        opening lines (before its first `##`) name no index file (README/behaviour/interface.md);
      - a doc/<pkg>/*.md (not devices/ or sources/) other than notes.md, design.md, tests.md and
        background*.md, not named in that package's notes.md or design.md,
  * a plans/*.md with a line `Master: plans/<x>.md` names a master that does not exist, or a
    master that does not name the sub-plan's filename (.claude/rules/plans.md "Splitting a plan").

Warns (exit code unchanged) when:
  * a design doc has a history marker outside code fences (a date, `pre-#n`, `since #n`,
    "originally", "previously", "formerly", "no longer"): K-4 keeps design docs history-free; the
    warning becomes an error once the existing docs are clean,
  * a device interface.md has no `## Access` heading (.claude/rules/devices.md),
  * a file is over its SIZE_CAPS warn level, a SKILL.md is over 500 lines, or a design-doc section
    is over 3000 chars,
  * a design doc anchors `(device <ID>)` whose source line carries only `[ASSUMED]`, outside a
    Known gaps heading (K-4 device facts),
  * an evidence row is over 400 chars,
  * agent knowledge (.claude/, doc/, packages/, tests/, custom_templates/) names background*.md or
    doc/sources/; exempt: doc/KNOWLEDGE.md, CLAUDE.md, the record-learning SKILL, plans/ (K-1).

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
# Size caps in characters, the single source of the numbers (doc/KNOWLEDGE.md K-1.2):
# (glob from the repo root, hard cap = error, warn level = warning, K-ref, measure).
# Measure: "text" = whole file, "body" = after the frontmatter, "description" = the skill's
# `description:` (checked by check_skill_frontmatter). Each real file takes the FIRST matching row,
# so specific rows come before the catch-all ones (device topic files, package reference docs).
SIZE_CAPS = [
    ("CLAUDE.md", 8000, 7000, "K-1.2", "text"),
    ("doc/KNOWLEDGE.md", 30000, 26000, "K-1.2", "text"),
    ("doc/*/notes.md", 24000, 21600, "K-3", "text"),
    ("doc/*/tests.md", 8000, 6000, "K-3", "text"),
    ("doc/*/design.md", 40000, 24000, "K-4", "text"),
    # Device files are read one decision at a time (K-1.2, .claude/rules/devices.md Parts):
    # README: read at the start of every device task, so the smallest.
    ("doc/devices/*/README.md", 8000, 6000, "K-1.2", "text"),
    # behaviour.md: index (States summary, Control, Does not work) plus subsystems until split.
    ("doc/devices/*/behaviour.md", 12000, 10000, "K-1.2", "text"),
    # interface.md: index (access summary, Unusable) plus registers and access until split.
    ("doc/devices/*/interface.md", 12000, 10000, "K-1.2", "text"),
    # registers-<area>.md: one circuit's table, read whole to add or parse one of its registers.
    ("doc/devices/*/registers-*.md", 12000, 10000, "K-1.2", "text"),
    # access-<path>.md: one path (polling, writes, wiring), read with a register part.
    ("doc/devices/*/access-*.md", 12000, 10000, "K-1.2", "text"),
    # evidence*.md: looked up by T number (grep), rarely read whole; uncited rows go to the archive.
    ("doc/devices/*/evidence*.md", 16000, 12000, "K-1.2", "text"),
    # <topic>.md: one subsystem or lookup topic, one decision.
    ("doc/devices/*/*.md", 12000, 10000, "K-1.2", "text"),
    ("doc/*/*.md", 40000, 30000, "K-1.2", "text"),
    (".claude/rules/*.md", 5000, 4000, "K-1.2", "text"),
    (".claude/skills/*/SKILL.md", 20000, 12000, "K-1.2", "body"),
    (".claude/skills/*/**/*.md", 40000, 30000, "K-1.2", "text"),
    ("plans/*.md", 40000, 25000, "K-1.2", "text"),
    (".claude/skills/*/SKILL.md", 500, 400, "K-1.2", "description"),
]
# Extra warnings: SKILL.md line count, design-doc section length (K-1.2, K-4).
SKILL_WARN_LINES = 500
DESIGN_SECTION_WARN = 3000
# A design-doc section: from a `##`..`####` heading to the next one.
SECTION_HEAD_RE = re.compile(r"^#{2,4}\s", re.MULTILINE)
# A design-doc heading that carries a stable ID: `## PG-4`, `#### AF-7.1.1`, `### AF-5.3b`.
ID_HEAD_RE = re.compile(r"^#{2,4}\s+([A-Z]+-\d+(?:\.\d+)*[a-z]?)(?![\w-])", re.MULTILINE)
# Reference with path: doc/<pkg>/design.md#<ID> (a `<pkg>` placeholder never matches).
FULL_REF_RE = re.compile(r"doc/([\w-]+)/design\.md#([A-Z]+-\d+(?:\.\d+)*[a-z]?)(?![\w-])")
# History markers a current-architecture doc should not need (warning only, see docstring).
HISTORY_RE = re.compile(
    r"\b(?:20\d\d-\d\d-\d\d|pre-#\d+|since #\d+|originally|previously|formerly|no longer)\b",
    re.IGNORECASE,
)
# Device docs: required files and the headings each must have (K-9, .claude/rules/devices.md).
DEVICE_HEADINGS = {
    "README.md": ["References"],
    "behaviour.md": ["Control", "Does not work", "Open questions"],
    "interface.md": ["Unusable on this unit"],
    "evidence.md": [],
}
# Headings warned when missing (not yet an error: existing docs predate them).
DEVICE_HEADINGS_WARN = {"interface.md": ["Access"]}
# Device parts indexed by interface.md (rule: Parts); every other part by README or behaviour.md.
INTERFACE_PARTS = ("access-", "registers-")
# Device files that are indexes or the evidence table, not parts (K-1.3).
DEVICE_NON_PARTS = ("README.md", "behaviour.md", "interface.md")
# Evidence tag in brackets, not a markdown link `[text](url)`: `[T4]`, `[IA p.63]`, `[ASSUMED]`.
DEVICE_TAG_RE = re.compile(r"\[([A-Z][A-Z0-9-]*)((?:\s[^\]\n]*)?)\](?!\()")
# A T row of evidence.md: `| T<n> | <date> | <method> | <seen> | <grade> |`.
T_ROW_RE = re.compile(r"^\|\s*(T\d+)\s*\|(.*)$", re.MULTILINE)
# A References row: first cell is an uppercase ID.
REF_ROW_RE = re.compile(r"^\|\s*([A-Z][A-Z0-9-]*)\s*\|", re.MULTILINE)
# File types that can hold a design-ID reference.
REF_SUFFIXES = {".md", ".yaml", ".py", ".jinja"}
# README Identity row declaring the device's fact-ID prefix: `| Prefix | VWS |`.
PREFIX_ROW_RE = re.compile(r"^\|\s*Prefix\s*\|\s*([A-Z][A-Z0-9]*)\s*\|", re.MULTILINE)
# Anchor to a device fact outside its folder: `(device VWS-7)`, also `(device VWS-7, VWS-9)`.
DEVICE_CITE_RE = re.compile(r"\(device ([A-Z][A-Z0-9]*-\d+(?:,\s*[A-Z][A-Z0-9]*-\d+)*)\)")
# Top-level folders whose files may anchor device facts (rule: .claude/rules/devices.md).
DEVICE_CITE_DIRS = ("doc/", "packages/", "tests/", "plans/", "custom_templates/")
# Device evidence tags that must not appear outside doc/devices/: `[T4]`, `[IA p.63]`, `[IA §2]`.
STRAY_TAG_RE = re.compile(r"\[(?:T\d+|[A-Z][A-Z0-9-]*\s+(?:p\.|§)\s*\d+[^\]\n]*)\](?!\()")
# A plan file named in a device doc.
PLAN_NAME_RE = re.compile(r"plans/([\w.-]+\.md)")
# Evidence rows longer than this are warned (a row is evidence, not a story, K-9).
EVIDENCE_ROW_WARN = 400
# Mentions of guarded history/raw material that agent knowledge must not make (K-1).
BACKGROUND_RE = re.compile(r"background[\w*-]*\.md|doc/sources/")
# Agent-knowledge folders scanned for BACKGROUND_RE, and the files exempt from it (K-1).
AGENT_DIRS = (".claude/", "doc/", "packages/", "tests/", "custom_templates/")
BACKGROUND_EXEMPT = {"CLAUDE.md", "doc/KNOWLEDGE.md", ".claude/skills/record-learning/SKILL.md"}


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
    """Each design doc: a note listing it in `paths:`, history markers warned (K-4)."""
    for design in sorted((ROOT / "doc").glob("*/design.md")):
        rel = design.relative_to(ROOT).as_posix()
        text = design.read_text(encoding="utf-8")
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


def check_design_refs(errors, ids, prefixes):
    """Every design-ID reference must name an existing heading (K-4 IDs, K-5 pointers)."""
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


def strip_code_spans(text):
    """Drop inline `code` so a tag shown as an example never counts as a citation."""
    return re.sub(r"`[^`\n]*`", "", text)


def section(text, heading):
    """Return the body of `## <heading>` up to the next `## ` heading ('' if absent)."""
    m = re.search(r"^##\s+%s\s*$(.*?)(?=^##\s|\Z)" % re.escape(heading), text, re.M | re.S)
    return m.group(1) if m else ""


def device_md(dev):
    """Yield a device folder's markdown files; manufacturer copies under references/ skipped."""
    for path in sorted(dev.rglob("*.md")):
        if "references" not in path.relative_to(dev).parts:
            yield path


def check_devices(errors, warnings, design_prefixes):
    """Each device folder (K-9): files, headings, tags, T rows, prefix, fact IDs, plan names.

    Returns {fact ID: (file, source line)} for the `(device <ID>)` anchor check.
    """
    defs, owners = {}, {}
    for dev in sorted(p for p in (ROOT / "doc" / "devices").glob("*") if p.is_dir()):
        # `_template` (and any `_`-prefixed folder) holds placeholders, not a device.
        if dev.name.startswith("_"):
            continue
        rel = dev.relative_to(ROOT).as_posix()
        texts = {}
        # Minimal device: README.md is the folder's only top-level markdown file (rule: Minimal
        # device); it needs README + References rows only, no prefix, and cites only [<REF>] tags.
        minimal = not [f for f in dev.glob("*.md") if f.name != "README.md"]
        for name, headings in DEVICE_HEADINGS.items():
            if minimal and name != "README.md":
                continue
            path = dev / name
            if not path.is_file():
                errors.append(f"{rel}: missing {name} (doc/KNOWLEDGE.md#K-9)")
                continue
            texts[name] = strip_fences(path.read_text(encoding="utf-8"))
            for h in headings:
                if not re.search(r"^##\s+%s\s*$" % re.escape(h), texts[name], re.M):
                    errors.append(f"{rel}/{name}: no '## {h}' heading (.claude/rules/devices.md)")
            for h in DEVICE_HEADINGS_WARN.get(name, []):
                if not re.search(r"^##\s+%s\s*$" % re.escape(h), texts[name], re.M):
                    warnings.append(f"{rel}/{name}: no '## {h}' heading (.claude/rules/devices.md)")
        # Known T rows across evidence.md and evidence-archive.md: each needs a date and a grade,
        # and a T number exists once per device (never reused, K-9).
        t_ids = set()
        for ev in sorted(dev.glob("evidence*.md")):
            for line in strip_fences(ev.read_text(encoding="utf-8")).splitlines():
                m = T_ROW_RE.match(line)
                if not m:
                    continue
                tid, rest = m.groups()
                if tid in t_ids:
                    errors.append(f"{rel}/{ev.name}: {tid} defined twice across evidence*.md")
                t_ids.add(tid)
                cells = [c.strip() for c in rest.split("|")]
                if not cells or not re.fullmatch(r"20\d\d-\d\d(?:-\d\d)?", cells[0]):
                    errors.append(f"{rel}/{ev.name}: {tid} has no YYYY-MM[-DD] date")
                if "CONFIRMED" not in rest and "OBSERVED" not in rest:
                    errors.append(f"{rel}/{ev.name}: {tid} has no CONFIRMED/OBSERVED grade")
                if len(line) > EVIDENCE_ROW_WARN:
                    warnings.append(
                        f"{rel}/{ev.name}: {tid} row {len(line)} chars, warn above "
                        f"{EVIDENCE_ROW_WARN} (.claude/rules/devices.md)"
                    )
        refs = set(REF_ROW_RE.findall(section(texts.get("README.md", ""), "References")))
        refs.discard("ID")
        if minimal and "README.md" in texts and not refs:
            errors.append(f"{rel}/README.md: minimal device without a References row")
        # Fact-ID prefix: declared once, unique across devices, never a design-doc prefix.
        m = PREFIX_ROW_RE.search(section(texts.get("README.md", ""), "Identity"))
        prefix = m.group(1) if m else None
        if prefix is None and not minimal:
            errors.append(
                f"{rel}/README.md: no Identity row '| Prefix | <PFX> |' (.claude/rules/devices.md)"
            )
        elif prefix in owners:
            errors.append(f"{rel}/README.md: prefix {prefix} also used by {owners[prefix]}")
        elif prefix in design_prefixes:
            errors.append(
                f"{rel}/README.md: prefix {prefix} is the ID prefix of "
                f"doc/{design_prefixes[prefix]}/design.md"
            )
        if prefix:
            owners.setdefault(prefix, rel)
        # Fact ID definitions: first table cell or a leading bold bullet, once per folder.
        def_re = (
            re.compile(r"^(?:\|\s*|\s*[-*]\s+\*\*)(%s-\d+)(?:\*\*|\s*\|)" % prefix)
            if prefix
            else None
        )
        seen_ids = {}
        for path in device_md(dev):
            raw = path.read_text(encoding="utf-8")
            # Plans named by a device doc must exist (Open questions point to them).
            for plan in sorted(set(PLAN_NAME_RE.findall(raw))):
                if not (ROOT / "plans" / plan).is_file():
                    errors.append(f"{rel}/{path.name}: names plans/{plan}, which does not exist")
            if def_re is None:
                continue
            for n, line in enumerate(strip_fences(raw).splitlines(), 1):
                m = def_re.match(line)
                if not m:
                    continue
                fid = m.group(1)
                if fid in seen_ids:
                    errors.append(
                        f"{rel}/{path.name}:{n}: {fid} already defined in {seen_ids[fid]}"
                    )
                    continue
                seen_ids[fid] = f"{path.name}:{n}"
                defs[fid] = (f"{rel}/{path.name}", line)
        # Every tag in every markdown file of the device must resolve.
        for path in device_md(dev):
            raw = path.read_text(encoding="utf-8")
            for n, line in enumerate(strip_code_spans(strip_fences(raw)).splitlines(), 1):
                for tag, _ in DEVICE_TAG_RE.findall(line):
                    if tag == "ASSUMED":
                        continue
                    if re.fullmatch(r"T\d+", tag):
                        if minimal:
                            errors.append(
                                f"{rel}/{path.name}:{n}: [{tag}] in a minimal device: add the "
                                "other template files (.claude/rules/devices.md)"
                            )
                        elif tag not in t_ids:
                            errors.append(f"{rel}/{path.name}:{n}: [{tag}] has no evidence.md row")
                    elif tag not in refs:
                        errors.append(f"{rel}/{path.name}:{n}: [{tag}] not in README References")
    return defs


def heading_stack_iter(text):
    """Yield (line number, line, current heading texts by level) over text without fences."""
    stack = {}
    for n, line in enumerate(strip_fences(text).splitlines(), 1):
        m = re.match(r"(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            stack = {k: v for k, v in stack.items() if k < level}
            stack[level] = m.group(2)
        yield n, line, stack


def check_device_refs(errors, warnings, defs):
    """Every `(device <ID>)` anchor resolves; a design resting on an [ASSUMED] fact sits under
    Known gaps (K-4 device facts); device evidence tags never appear outside doc/devices/ (K-9)."""
    for name, path in ref_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        # Evidence tags outside the device folders: markdown only, code spans and fences ignored.
        if path.suffix == ".md" and not name.startswith("doc/devices/"):
            for n, line in enumerate(strip_code_spans(strip_fences(text)).splitlines(), 1):
                for m in STRAY_TAG_RE.finditer(line):
                    errors.append(
                        f"{name}:{n}: evidence tag {m.group(0)} outside doc/devices/: "
                        "cite `(device <ID>)` (doc/KNOWLEDGE.md#K-9)"
                    )
        if not name.startswith(DEVICE_CITE_DIRS) or name.startswith("doc/devices/_"):
            continue
        is_design = name.startswith("doc/") and path.name == "design.md"
        for n, line, stack in heading_stack_iter(text):
            for group in DEVICE_CITE_RE.findall(line):
                for fid in re.split(r",\s*", group):
                    if fid not in defs:
                        errors.append(f"{name}:{n}: (device {fid}) names no device fact ID")
                        continue
                    tags = {t for t, _ in DEVICE_TAG_RE.findall(strip_code_spans(defs[fid][1]))}
                    in_gaps = any("known gaps" in h.lower() for h in stack.values())
                    if is_design and tags == {"ASSUMED"} and not in_gaps:
                        warnings.append(
                            f"{name}:{n}: rests on {fid}, only [ASSUMED] in {defs[fid][0]}; "
                            "allowed under Known gaps only (doc/KNOWLEDGE.md#K-4)"
                        )


def frontmatter(text):
    """Return (frontmatter lines, body) of a `---` delimited header; (None, text) if absent."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    return None, text


def size_skipped(rel):
    """Never capped: templates, guarded history/raw material, manufacturer copies under
    doc/devices/<d>/references/ (K-1.2). Skill references/*.md are capped."""
    parts = rel.split("/")
    return (
        any(p.startswith("_") for p in parts[:-1])
        or parts[-1].startswith("background")
        or rel.startswith("doc/sources/")
        or (parts[:2] == ["doc", "devices"] and len(parts) > 4 and parts[3] == "references")
    )


def check_sizes(errors, warnings):
    """Every knowledge file against its first matching SIZE_CAPS row (K-1.2), by real path."""
    seen = set()
    for pattern, hard, warn, kref, measure in SIZE_CAPS:
        if measure == "description":
            continue
        for path in sorted(ROOT.glob(pattern)):
            rel = path.relative_to(ROOT).as_posix()
            real = path.resolve()
            if real in seen or not path.is_file() or size_skipped(rel):
                continue
            seen.add(real)
            text = real.read_text(encoding="utf-8")
            measured = frontmatter(text)[1] if measure == "body" else text
            size = len(measured)
            if size > hard:
                errors.append(f"{rel}: {size} chars, cap {hard} (doc/KNOWLEDGE.md#{kref})")
            elif size > warn:
                warnings.append(f"{rel}: {size} chars, warn above {warn} (doc/KNOWLEDGE.md#{kref})")
            if path.name == "SKILL.md" and len(text.splitlines()) > SKILL_WARN_LINES:
                warnings.append(
                    f"{rel}: {len(text.splitlines())} lines, warn above {SKILL_WARN_LINES} "
                    "(doc/KNOWLEDGE.md#K-1.2)"
                )
            if path.name == "design.md":
                body = strip_fences(text)
                starts = [m.start() for m in SECTION_HEAD_RE.finditer(body)] + [len(body)]
                for a, b in zip(starts, starts[1:]):
                    if b - a > DESIGN_SECTION_WARN:
                        head = body[a:body.find("\n", a)].strip()[:60]
                        warnings.append(
                            f"{rel}: section '{head}' {b - a} chars, warn above "
                            f"{DESIGN_SECTION_WARN} (doc/KNOWLEDGE.md#K-4)"
                        )


def check_skill_frontmatter(errors, warnings):
    """Each SKILL.md has `name:` and `description:`; the description stays under its cap (K-1.2)."""
    _, hard, warn, kref, _ = next(r for r in SIZE_CAPS if r[4] == "description")
    for skill in sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md")):
        rel = skill.relative_to(ROOT).as_posix()
        head, _ = frontmatter(skill.read_text(encoding="utf-8"))
        if head is None:
            errors.append(f"{rel}: no `---` frontmatter")
            continue
        keys, desc, cur = set(), [], None
        for line in head:
            m = re.match(r"([\w-]+):\s*(.*)$", line)
            if m:
                cur = m.group(1)
                keys.add(cur)
                if cur == "description" and m.group(2) not in (">", "|", ">-", "|-", ""):
                    desc.append(m.group(2))
            elif cur == "description" and line.strip():
                # Folded or literal block scalar continuation.
                desc.append(line.strip())
        for key in ("name", "description"):
            if key not in keys:
                errors.append(f"{rel}: frontmatter has no `{key}:`")
        size = len(" ".join(desc))
        if size > hard:
            errors.append(f"{rel}: description {size} chars, cap {hard} (doc/KNOWLEDGE.md#{kref})")
        elif size > warn:
            warnings.append(
                f"{rel}: description {size} chars, warn above {warn} (doc/KNOWLEDGE.md#{kref})"
            )


def check_rule_frontmatter(errors):
    """Each rule (symlinked notes too): `---` / `paths:` list / `---`, no `@` line (K-1, K-8)."""
    for rule in sorted((ROOT / ".claude" / "rules").rglob("*.md")):
        rel = rule.relative_to(ROOT).as_posix()
        if not rule.is_file():
            continue  # dangling symlink: check_package_notes reports it
        text = rule.read_text(encoding="utf-8")
        head, _ = frontmatter(text)
        if head is None:
            errors.append(f"{rel}: no `---` ... `---` frontmatter (a broken one loads always, K-8)")
        elif not note_paths(rule):
            errors.append(f"{rel}: frontmatter has no `paths:` list")
        for n, line in enumerate(text.splitlines(), 1):
            if line.startswith("@"):
                errors.append(f"{rel}:{n}: line starts with '@' (eager import, K-1)")


def unindexed(parts, indexes, base):
    """Return the parts that no index file names, by path relative to `base` or by basename."""
    text = "\n".join(i.read_text(encoding="utf-8") for i in indexes if i.is_file())
    return [
        p for p in parts
        if p.relative_to(base).as_posix() not in text and p.name not in text
    ]


def check_reference_index(errors):
    """Every reference part is named by its index, so a read-when pointer reaches it (K-1.3)."""
    # Skill detail files: indexed in the skill's SKILL.md.
    for skill in sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md")):
        parts = [p for p in sorted(skill.parent.rglob("*.md")) if p != skill]
        for p in unindexed(parts, [skill], skill.parent):
            errors.append(
                f"{p.relative_to(ROOT).as_posix()}: not named in "
                f"{skill.relative_to(ROOT).as_posix()} (doc/KNOWLEDGE.md#K-1.3)"
            )
    # Device parts: access-*/registers-* indexed in interface.md, other topic files in the
    # README file map or behaviour.md; each opens (before its first `##`) naming its index.
    for dev in sorted(p for p in (ROOT / "doc" / "devices").glob("*") if p.is_dir()):
        if dev.name.startswith("_"):
            continue
        parts = [
            p for p in sorted(dev.glob("*.md"))
            if p.name not in DEVICE_NON_PARTS and not p.name.startswith("evidence")
        ]
        iface = [p for p in parts if p.name.startswith(INTERFACE_PARTS)]
        topics = [p for p in parts if p not in iface]
        for p in unindexed(iface, [dev / "interface.md"], dev):
            errors.append(
                f"{p.relative_to(ROOT).as_posix()}: not named in interface.md "
                "(.claude/rules/devices.md Parts, doc/KNOWLEDGE.md#K-1.3)"
            )
        for p in unindexed(topics, [dev / "README.md", dev / "behaviour.md"], dev):
            errors.append(
                f"{p.relative_to(ROOT).as_posix()}: not named in README.md file map or "
                "behaviour.md (doc/KNOWLEDGE.md#K-1.3)"
            )
        for p in parts:
            # Opening = text after the `#` title up to the first `##` heading, banners included.
            head = re.split(r"^##\s", strip_fences(p.read_text(encoding="utf-8")), maxsplit=1, flags=re.M)[0]
            if not re.search(r"\b(?:README|behaviour|interface)\.md\b", head):
                errors.append(
                    f"{p.relative_to(ROOT).as_posix()}: opening lines name no index file "
                    "(README.md, behaviour.md or interface.md; doc/KNOWLEDGE.md#K-1.3)"
                )
    # Package reference docs: indexed in the package note (header) or design doc.
    for pkg in sorted(p for p in (ROOT / "doc").glob("*") if p.is_dir()):
        if pkg.name in ("devices", "sources"):
            continue
        parts = [
            p for p in sorted(pkg.glob("*.md"))
            if p.name not in ("notes.md", "design.md", "tests.md")
            and not p.name.startswith("background")
        ]
        for p in unindexed(parts, [pkg / "notes.md", pkg / "design.md"], pkg):
            errors.append(
                f"{p.relative_to(ROOT).as_posix()}: not named in doc/{pkg.name}/notes.md or "
                "design.md (doc/KNOWLEDGE.md#K-1.3)"
            )


# Sub-plan header naming its master plan (.claude/rules/plans.md "Splitting a plan").
MASTER_RE = re.compile(r"^Master:\s*plans/([\w.-]+\.md)", re.MULTILINE)


def check_plan_masters(errors):
    """A sub-plan's `Master:` names an existing plan, and that master names the sub-plan."""
    for plan in sorted((ROOT / "plans").glob("*.md")):
        m = MASTER_RE.search(plan.read_text(encoding="utf-8"))
        if not m:
            continue
        rel = plan.relative_to(ROOT).as_posix()
        master = ROOT / "plans" / m.group(1)
        if master == plan or not master.is_file():
            errors.append(f"{rel}: Master plans/{m.group(1)} is missing or the plan itself")
        elif plan.name not in master.read_text(encoding="utf-8"):
            errors.append(f"{rel}: master plans/{m.group(1)} does not name {plan.name}")


def check_no_background_refs(warnings):
    """Agent knowledge never names background or sources (K-1); warning only."""
    for name, path in ref_files():
        if not name.startswith(AGENT_DIRS) or name in BACKGROUND_EXEMPT:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            m = BACKGROUND_RE.search(line)
            if m:
                warnings.append(f"{name}:{n}: names '{m.group(0)}' (doc/KNOWLEDGE.md#K-1)")


def main():
    errors, warnings = [], []
    check_plans(errors)
    check_package_notes(errors)
    check_design_docs(errors, warnings)
    ids, prefixes = design_ids(errors)
    check_design_refs(errors, ids, prefixes)
    defs = check_devices(errors, warnings, prefixes)
    check_device_refs(errors, warnings, defs)
    check_sizes(errors, warnings)
    check_skill_frontmatter(errors, warnings)
    check_rule_frontmatter(errors)
    check_reference_index(errors)
    check_plan_masters(errors)
    check_no_background_refs(warnings)
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
