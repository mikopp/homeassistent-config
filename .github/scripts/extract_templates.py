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

# HA template functions, Jinja2 built-ins, and Python primitives that are
# always available in every template evaluation context (not "free variables").
_KNOWN_NAMES = frozenset({
    # Jinja2 / Python builtins
    "namespace", "range", "loop", "true", "false", "none",
    "True", "False", "None", "not", "and", "or", "is", "in",
    "if", "else", "elif", "for", "endfor", "set", "do",
    "dict", "list", "tuple", "set", "str", "int", "float", "bool", "len",
    "zip", "map", "filter", "select", "reject", "items", "max", "min",
    # Math (exposed in HA Jinja2 environment)
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sqrt",
    "log", "pi", "e", "tau", "floor", "ceil", "round", "abs",
    # HA global template functions
    "states", "state_attr", "is_state", "is_state_attr", "has_value",
    "state_translated", "device_attr", "is_device_attr",
    "area_id", "area_name", "area_entities", "area_devices",
    "expand", "closest", "distance",
    "now", "today_at", "utcnow", "as_datetime", "as_timestamp",
    "relative_time", "timedelta", "strptime", "as_local", "as_utc",
    "iif",
    # Common Jinja2 filter names (used as `| filtername`)
    "default", "join", "split", "replace", "trim", "upper", "lower",
    "title", "capitalize", "first", "last", "reverse", "sort", "unique",
    "count", "batch", "slice", "indent", "wordcount", "truncate",
    "urlencode", "xmlattr", "striptags", "escape", "safe",
    "tojson", "fromjson", "pprint", "string",
})

# Matches identifiers used in expressions that are NOT preceded by a '(' or '.' or
# quote (which would mean they are arguments inside a call or attribute access).
_IDENTIFIER_RE = re.compile(r"(?<![(\w.'\"\\])\b([a-z_][a-z0-9_]*)\b")
# Matches filter names: `| filtername`
_FILTER_NAME_RE = re.compile(r"\|\s*([a-z_]\w*)")
# Matches locally-defined names: `{% set varname`
_SET_VAR_RE = re.compile(r"\{%-?\s*set\s+(\w+)")


def _has_free_variables(template: str) -> bool:
    """Return True when template references identifiers not defined within it.

    Catches templates that depend on script field parameters or script-local
    variables set in a previous step (e.g. ``slat_angle``, ``_tilt``).
    These cannot be evaluated standalone because the external variables are
    injected only when the script/automation is executing.
    """
    # Names introduced by {% set %} within this template
    locally_defined = set(_SET_VAR_RE.findall(template))
    # Filter names are part of Jinja2 syntax, not variable references
    filter_names = set(_FILTER_NAME_RE.findall(template))
    safe = _KNOWN_NAMES | locally_defined | filter_names

    for m in _IDENTIFIER_RE.finditer(template):
        name = m.group(1)
        if name not in safe:
            return True
    return False


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
    """Return True when the template references runtime-only or free variables."""
    return bool(_RUNTIME_VARS.search(template)) or _has_free_variables(template)


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
