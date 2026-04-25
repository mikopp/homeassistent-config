#!/usr/bin/env python3
"""Extract Jinja2 template strings from Home Assistant YAML config files.

Usage: python extract_templates.py [repo_root]
  repo_root defaults to the current directory.

Outputs a JSON object with two keys to stdout:
  state_templates   — templates that only reference state/input entities; safe for
                      strict validation after state is seeded.
  runtime_templates — templates that reference runtime-only variables (trigger, wait,
                      value, repeat, this, context); validated leniently (syntax only).
"""

import json
import re
import sys
from pathlib import Path

import yaml


# Variables that only exist at automation/script execution time.
# Templates referencing these cannot be evaluated outside a live execution context.
_RUNTIME_VARS = re.compile(
    r"\b(trigger|wait|value|repeat|this|context)\b"
)


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


def _collect(value, out, file_path):
    """Recursively collect template strings from a parsed YAML value."""
    if isinstance(value, str):
        if "{{" in value or "{%" in value:
            out.append({"template": value, "file": file_path})
    elif isinstance(value, dict):
        for v in value.values():
            _collect(v, out, file_path)
    elif isinstance(value, list):
        for item in value:
            _collect(item, out, file_path)


def _is_runtime(template):
    """Return True when the template references runtime-only variables."""
    return bool(_RUNTIME_VARS.search(template))


def extract_templates(repo_root):
    """Return {"state_templates": [...], "runtime_templates": [...]}."""
    root = Path(repo_root).resolve()
    raw = []

    for path in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
        # Skip CI/tooling files — they are not HA config
        if ".github" in path.parts:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = yaml.load(fh, Loader=_LOADER)
            rel = str(path.relative_to(root))
            _collect(data, raw, rel)
        except yaml.YAMLError:
            # YAML errors are caught by the yaml-lint job; skip here
            pass

    # Deduplicate by template string, keeping first-seen file
    seen = set()
    unique = []
    for item in raw:
        if item["template"] not in seen:
            seen.add(item["template"])
            unique.append(item)

    # Split into state-resolvable vs runtime-only
    state_templates = [t for t in unique if not _is_runtime(t["template"])]
    runtime_templates = [t for t in unique if _is_runtime(t["template"])]

    return {"state_templates": state_templates, "runtime_templates": runtime_templates}


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    result = extract_templates(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
