#!/usr/bin/env bash
# Run the CI checks locally: the YAML checks (mirrors yaml-lint.yml), a smoke run of the template
# extractor, and the in-process test suite tests/ha (mirrors tests.yaml, no Docker needed to run
# it). The real-HA layer tests/e2e (e2e.yaml) needs Docker and runs only with --e2e.
#
# Prerequisites (macOS): brew install python@3.15 python@3.14 mosquitto (yamllint is installed
# into .venv)
#   - python@3.14: the in-process suite runs on the Python Home Assistant requires
#     (.github/ha-versions/ha-python.txt); without it that step is SKIPPED, loudly.
#   - mosquitto: must be the version pinned in .github/ha-versions/mosquitto/Dockerfile (the Home
#     Assistant Mosquitto app's). On Linux with Docker the script installs it by itself
#     (.github/scripts/install-mosquitto.sh); elsewhere install that version yourself, or the
#     step fails with the fix (tests/ha/test_versions.py is the check).
# Usage:  .github/scripts/ci-local.sh [--e2e]        (run from anywhere)
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
  # The Docker-free checks below need just pyyaml, so fall back to those.
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

# Smoke run of the extractor (tests/ha/test_templates.py renders its output).
extract_templates() {
  "$VENV/bin/python" .github/scripts/extract_templates.py . > "$TMP/templates.json"
}

step "YAML style (fix_yaml_style.py)" style_check
step "yamllint" "$YAMLLINT" -c .yamllint.yaml .
step "yamllint on resolved config + dashboards" lint_resolved
step "Jinja template extraction" extract_templates
# Plans need Status + Close, packages need a note symlink (doc/KNOWLEDGE.md K-6, K-8).
step "knowledge layout" "$VENV/bin/python" .github/scripts/check_knowledge_layout.py

# ── In-process suite (tests/ha), as in tests.yaml ────────────────────────────────────────────────
SKIPPED=()
HAPY=$(tr -d '[:space:]' < .github/ha-versions/ha-python.txt)
PY_TEST=$(command -v "python$HAPY" || true)
if [ -z "$PY_TEST" ]; then
  echo "── In-process tests (tests/ha)"
  echo "   SKIPPED: python$HAPY not found (the Python Home Assistant requires); brew install python@$HAPY"
  SKIPPED+=("tests/ha")
else
  # A second venv, same recipe as .venv above: Home Assistant (PHACC) needs its own Python.
  if [ ! -x .venv-test/bin/python ]; then "$PY_TEST" -m venv .venv-test || exit 1; fi
  # (a venv made by `uv venv` has no pip; use uv then)
  if [ -x .venv-test/bin/pip ]; then
    .venv-test/bin/pip install --quiet -r requirements_test.txt || exit 1
  else
    VIRTUAL_ENV="$PWD/.venv-test" uv pip install --quiet -r requirements_test.txt || exit 1
  fi
  # climate_template into custom_components/ (the one shared installer; skips if present).
  "$VENV/bin/python" .github/scripts/install_custom_components.py || exit 1

  # The pinned mosquitto: a copy extracted by install-mosquitto.sh wins over the system one.
  export PATH="$PWD/.cache/mosquitto/bin:$PATH"
  MQ_FILE=.github/ha-versions/mosquitto/Dockerfile
  MQ_APP=$(awk -F: '/^FROM /{print $2}' "$MQ_FILE")
  MQ_WANT=$(sed -n "s/^# mosquitto-in-app: $MQ_APP = //p" "$MQ_FILE")
  mq_have() { mosquitto -h 2>&1 | sed -n 's/^mosquitto version //p' | head -1; }
  if [ "$(mq_have)" != "$MQ_WANT" ] && [ "$(uname -s)" = "Linux" ] && command -v docker >/dev/null; then
    .github/scripts/install-mosquitto.sh || true
  fi
  # No special case if it is still wrong: tests/ha/test_versions.py fails with the fix.
  echo "   mosquitto $(mq_have) (pinned: ${MQ_WANT:-?}, app $MQ_APP)"
  step "In-process tests (tests/ha)" .venv-test/bin/python -m pytest \
    -c tests/ha/pytest.ini --confcutdir tests/ha --rootdir . tests/ha -n auto --timeout=60 -q
fi

# ── Real-HA layer (tests/e2e), opt-in: needs Docker and takes a few minutes ─────────────────────
if [ "${1:-}" = "--e2e" ]; then
  if ! command -v docker >/dev/null; then
    echo "── Real-HA tests (tests/e2e)"; echo "   FAILED: --e2e needs docker"; FAILED+=("tests/e2e")
  else
    # Own venv: its pins (pytest 9.2) differ from the PHACC ones.
    [ -x .venv-e2e/bin/python ] || "${PY_TEST:-$PY}" -m venv .venv-e2e || exit 1
    .venv-e2e/bin/pip install --quiet -r tests/e2e/requirements.txt || exit 1
    step "Real-HA tests (tests/e2e)" .venv-e2e/bin/python -m pytest \
      -c tests/e2e/pytest.ini --confcutdir tests/e2e --rootdir . tests/e2e \
      -p no:homeassistant --timeout=300 --timeout-method=thread
  fi
else
  SKIPPED+=("tests/e2e (needs Docker, run with --e2e)")
fi

if [ ${#SKIPPED[@]} -gt 0 ]; then echo; echo "Skipped (NOT checked): ${SKIPPED[*]}"; fi

if [ ${#FAILED[@]} -gt 0 ]; then
  echo; echo "Failed: ${FAILED[*]}"; exit 1
fi
echo; echo "All local checks passed."
