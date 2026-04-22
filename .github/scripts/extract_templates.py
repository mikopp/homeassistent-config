#!/usr/bin/env python3
"""Extract Jinja2 template strings from Home Assistant YAML config files.

Usage: python extract_templates.py [repo_root]
  repo_root defaults to the current directory.
Outputs a JSON array of unique template strings to stdout.
"""

import json
import os
import sys
from pathlib import Path

import yaml


def _make_loader():
    """Build a YAML loader that no-ops all HA custom tags."""
    class HALoader(yaml.SafeLoader):
        pass

    def _noop(loader, node):
        return loader.construct_scalar(node)

    for tag in (
        "!secret",
        "!include",
        "!include_dir_named",
        "!include_dir_merge_named",
        "!include_dir_list",
        "!include_dir_merge_list",
    ):
        HALoader.add_constructor(tag, _noop)

    return HALoader


_LOADER = _make_loader()


def _collect(value, out):
    """Recursively collect template strings from a parsed YAML value."""
    if isinstance(value, str):
        if "{{" in value or "{%" in value:
            out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _collect(v, out)
    elif isinstance(value, list):
        for item in value:
            _collect(item, out)


def extract_templates(repo_root):
    root = Path(repo_root).resolve()
    raw = []

    for path in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
        # Skip CI/tooling files — they are not HA config
        if ".github" in path.parts:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = yaml.load(fh, Loader=_LOADER)
            _collect(data, raw)
        except yaml.YAMLError:
            # YAML errors are caught by the yaml-lint job; skip here
            pass

    # Deduplicate, preserving first-seen order
    seen = set()
    unique = []
    for t in raw:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    templates = extract_templates(root)
    print(json.dumps(templates, ensure_ascii=False, indent=2))
