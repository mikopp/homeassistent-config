#!/usr/bin/env python3
"""Assert that a YAML file's data is unchanged against a git ref.

Usage:  .github/scripts/yaml_semantic_equal.py [--ignore-jinja-comments] <before-ref> <file> [<file> ...]

Used for comment-only edits (knowledge dedup, doc/KNOWLEDGE.md#K-5): it parses
`git show <ref>:<file>` and the working copy and compares the two data trees.
YAML comments are not part of the data, so moving or rewording `#` comments
passes. Any change to keys, values, list order or template strings fails,
including Jinja `{# #}` comments, which are template text.

--ignore-jinja-comments: render-equivalence mode for dedup of comments inside templates.
Every string (and every *.jinja file as a whole) is compared after removing `{# ... #}`
comments and collapsing whitespace runs to one space. Comments never render, so templates that
differ only in comment text (and the whitespace around it) still compare equal. Any change to
code, quoted literals, or the order of statements still fails. Whitespace-control markers
(`{#-` / `-#}`) are covered by the whitespace collapse. Not proof for text whose exact
whitespace is output (none of the comment-bearing airflow templates are such); CI tests remain
the behavioural check.

Exit status: 0 if every file is equal, 1 if any differs, 2 on usage/git errors.
"""

import re
import subprocess
import sys

import yaml


# ── Loader: accept Home Assistant tags as opaque values ─────────────────────
# HA YAML uses custom tags (!include, !secret, !input, !include_dir_named, ...).
# SafeLoader rejects unknown tags, so register a catch-all constructor that
# turns any tagged node into a (tag, value) tuple. The tag and its argument are
# then compared like any other value, without resolving the include.
class HALoader(yaml.SafeLoader):
    """SafeLoader that keeps unknown `!tags` as (tag, value) tuples."""


def _opaque_tag(loader, tag_suffix, node):
    # tag_suffix is the part after "!" (e.g. "include"); keep it and the raw value.
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = tuple(loader.construct_sequence(node, deep=True))
    else:
        value = tuple(sorted(loader.construct_mapping(node, deep=True).items()))
    return ("!" + tag_suffix, value)


HALoader.add_multi_constructor("!", _opaque_tag)


# ── Inputs: the file at <ref> (via git) and the working copy ────────────────
def load_at_ref(ref, path):
    """Parse `path` as it is in git at `ref`."""
    text = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if path.endswith(".jinja"):
        return text  # a macro file is one template string, not YAML
    return yaml.load(text, Loader=HALoader)


def load_working(path):
    """Parse the working-copy version of `path`."""
    with open(path, encoding="utf-8") as fh:
        if path.endswith(".jinja"):
            return fh.read()
        return yaml.load(fh, Loader=HALoader)


# ── Optional normalisation: ignore Jinja comments and whitespace in strings ─
_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)


def normalise(value):
    """Return `value` with Jinja comments removed and whitespace collapsed in every string."""
    if isinstance(value, str):
        return " ".join(_JINJA_COMMENT.sub("", value).split())
    if isinstance(value, dict):
        return {k: normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalise(v) for v in value]
    if isinstance(value, tuple):
        return tuple(normalise(v) for v in value)
    return value


# ── Diff: report the first differing path so a failure is easy to find ──────
def first_difference(a, b, where="$"):
    """Return a description of the first difference between a and b, or None."""
    if type(a) is not type(b):
        return f"{where}: type {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        if set(a) != set(b):
            return f"{where}: keys differ: -{sorted(set(a) - set(b), key=str)} +{sorted(set(b) - set(a), key=str)}"
        for key in a:
            diff = first_difference(a[key], b[key], f"{where}.{key}")
            if diff:
                return diff
        return None
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return f"{where}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            diff = first_difference(x, y, f"{where}[{i}]")
            if diff:
                return diff
        return None
    return None if a == b else f"{where}: {a!r} != {b!r}"


# ── Main: compare each file, print OK/DIFF, exit non-zero on any difference ─
def main(argv):
    args = argv[1:]
    ignore_comments = "--ignore-jinja-comments" in args
    args = [a for a in args if a != "--ignore-jinja-comments"]
    if len(args) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    ref, paths = args[0], args[1:]
    failed = False
    for path in paths:
        try:
            before = load_at_ref(ref, path)
        except subprocess.CalledProcessError as err:
            print(f"ERROR {path}: git show {ref}:{path} failed: {err.stderr.strip()}", file=sys.stderr)
            return 2
        after = load_working(path)
        if ignore_comments:
            before, after = normalise(before), normalise(after)
        diff = first_difference(before, after)
        if diff:
            failed = True
            print(f"DIFF  {path}: {diff}")
        else:
            print(f"OK    {path}: data identical to {ref}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
