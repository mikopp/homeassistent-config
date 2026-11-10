#!/usr/bin/env bash
# Run the Docker-free CI checks locally (mirrors yaml-lint.yml and the
# template-extraction step of ha_check.yaml). Not covered here, because they
# need Docker: `check_config` and all pytest runs.
#
# Prerequisites: python3 (macOS: brew install python@3.15). yamllint is installed into .venv.
# Usage:  .github/scripts/ci-local.sh        (run from anywhere)
set -u

# Work from the repo root so relative paths match CI.
cd "$(git rev-parse --show-toplevel)" || exit 1

VENV=.venv
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILED=()

# Pick the Python pinned for CI (.github/ha-versions/python/Dockerfile), falling
# back to plain python3 if that exact minor version is not installed.
PYVER=$(awk -F'[:@ ]' '/^FROM /{print $3}' .github/ha-versions/python/Dockerfile)
PY=$(command -v "python$PYVER" || command -v python3) || { echo "No python3 found"; exit 1; }

# Create the venv once and (re)install CI Python deps from the same manifest CI uses.
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV" || exit 1
fi
if ! "$VENV/bin/pip" install --quiet -r .github/workflows/requirements.txt; then
  # The test harness needs the pinned (newer) Python and is only used by pytest, which runs in CI.
  # The Docker-free checks below need just pyyaml + requests, so fall back to those.
  echo "WARN: full CI manifest not installable on $("$VENV/bin/python" --version); installing Docker-free deps only"
  "$VENV/bin/pip" install --quiet pyyaml requests || exit 1
fi
# yamllint comes from the venv, so no system install (brew/apt) is needed locally or in cloud sessions.
"$VENV/bin/pip" install --quiet yamllint || exit 1
YAMLLINT="$VENV/bin/yamllint"
echo "Using $("$VENV/bin/python" --version) (CI pin: $PYVER)"

# step <name> <command...>: run a check, record failures, keep going.
step() {
  local name=$1; shift
  echo "── $name"
  if "$@"; then echo "   ok"; else echo "   FAILED"; FAILED+=("$name"); fi
}

# fix_yaml_style.py rewrites files in place; CI fails if that changes anything.
# Compare the diff before/after so a dirty working tree does not cause a false alarm.
style_check() {
  local before after
  before=$(git diff | shasum)
  "$VENV/bin/python" .github/scripts/fix_yaml_style.py . || return 1
  after=$(git diff | shasum)
  [ "$before" = "$after" ] || { echo "   style fixer changed files; review with git diff"; return 1; }
}

# Resolve !include directives, then lint the flattened result (lint-resolved job).
lint_resolved() {
  local f out rc=0
  for f in configuration.yaml dashboards/*.yaml; do
    out="$TMP/resolved_$(basename "$f")"
    "$VENV/bin/python" .github/scripts/resolve_ha_yaml.py "$f" . > "$out" || { rc=1; continue; }
    "$YAMLLINT" -c .yamllint.yaml "$out" || rc=1
  done
  return $rc
}

# Same template extraction ha_check.yaml does before pytest.
extract_templates() {
  "$VENV/bin/python" .github/scripts/extract_templates.py . > "$TMP/templates.json"
}

step "YAML style (fix_yaml_style.py)" style_check
step "yamllint" "$YAMLLINT" -c .yamllint.yaml .
step "yamllint on resolved config + dashboards" lint_resolved
step "Jinja template extraction" extract_templates
# Plans need Status + Close, packages need a note symlink (doc/KNOWLEDGE.md K-6, K-8).
step "knowledge layout" "$VENV/bin/python" .github/scripts/check_knowledge_layout.py

if [ ${#FAILED[@]} -gt 0 ]; then
  echo; echo "Failed: ${FAILED[*]}"; exit 1
fi
echo; echo "All local checks passed."
