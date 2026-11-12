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
#
# Usage (run from anywhere):
#   ci-local.sh                      full run: all YAML checks + all of tests/ha (the pre-push check)
#   ci-local.sh --e2e                full run plus tests/e2e (Docker)
#   ci-local.sh --package NAME       targeted: tests/ha tests of packages/NAME.yaml (repeatable)
#   ci-local.sh -- PYTEST_ARGS...    targeted: everything after -- goes verbatim to the tests/ha
#                                    pytest call (test ids, -k, -x, --count=20, -n 0 ...)
#   ci-local.sh --yaml               targeted: only the YAML / knowledge-layout checks, no tests
# --package, -- and --yaml are combinable. Any of them makes a TARGETED RUN: the YAML checks are
# skipped (unless --yaml) and the summary says it is not a full verification. --e2e cannot be
# combined with them (tests/e2e has no per-package split). Exit codes: 0 ok, 1 a check failed,
# 2 usage error.
set -u

# usage_error <message>: print the message and the usage line, exit 2.
usage_error() {
  echo "ci-local.sh: $1" >&2
  echo "usage: ci-local.sh [--e2e | [--yaml] [--package NAME]... [-- PYTEST_ARGS...]]" >&2
  exit 2
}

# Work from the repo root so relative paths match CI.
cd "$(git rev-parse --show-toplevel)" || exit 1

# ── Arguments ────────────────────────────────────────────────────────────────────────────────────
# Valid package names are the packages/*.yaml basenames; checked before any slow setup (fail fast).
PACKAGES=()
for f in packages/*.yaml; do f=${f#packages/}; PACKAGES+=("${f%.yaml}"); done
E2E=0; YAML_ONLY=0; PKG_ARGS=(); PYTEST_EXTRA=(); SELECTED=0
while [ $# -gt 0 ]; do
  case $1 in
    --e2e) E2E=1 ;;
    --yaml) YAML_ONLY=1; SELECTED=1 ;;
    --package)
      [ $# -ge 2 ] || usage_error "--package needs a NAME"
      case " ${PACKAGES[*]} " in
        *" $2 "*) ;;
        *) echo "ci-local.sh: unknown package '$2'. Valid packages: ${PACKAGES[*]}" >&2; exit 2 ;;
      esac
      PKG_ARGS+=(--package "$2"); SELECTED=1; shift ;;
    --) shift; PYTEST_EXTRA=("$@"); SELECTED=1; break ;;
    *) usage_error "unknown option '$1'" ;;
  esac
  shift
done
[ "$E2E" = 1 ] && [ "$SELECTED" = 1 ] && usage_error "--e2e cannot be combined with --yaml, --package or -- (e2e has no per-package split)"

# Which parts run: a full run does both; a targeted run runs the YAML checks only on --yaml and the
# tests unless --yaml was the only selection.
RUN_YAML=1; RUN_TESTS=1
if [ "$SELECTED" = 1 ]; then
  RUN_YAML=$YAML_ONLY
  if [ "$YAML_ONLY" = 1 ] && [ ${#PKG_ARGS[@]} -eq 0 ] && [ ${#PYTEST_EXTRA[@]} -eq 0 ]; then RUN_TESTS=0; fi
fi

VENV=.venv
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILED=()

# Pick the Python pinned for CI (.github/ha-versions/python/Dockerfile), falling
# back to plain python3 if that exact minor version is not installed.
PYVER=$(awk -F'[:@ ]' '/^FROM /{print $3}' .github/ha-versions/python/Dockerfile)
PY=$(command -v "python$PYVER" || command -v python3) || { echo "No python3 found"; exit 1; }

# sha256_of: sha256 of stdin (sha256sum on Linux, shasum on macOS, which has no sha256sum).
sha256_of() {
  if command -v sha256sum >/dev/null; then sha256sum | cut -d' ' -f1; else shasum -a 256 | cut -d' ' -f1; fi
}

# install_once <venv> <name> <file>... -- <install command...>: run the install only when its input
# changed. The stamp <venv>/.ci-local-<name>.sha256 holds the hash of the file contents, the venv's
# python version and the command; it is written only after a successful install, so a failed or
# partial install (and a new venv, which has no stamp) always runs again. pip's own resolve takes
# seconds even when nothing changed. Returns the install's exit code (0 when skipped).
install_once() {
  local venv=$1 name=$2 files=() stamp want
  shift 2
  while [ "$1" != "--" ]; do files+=("$1"); shift; done
  shift
  stamp="$venv/.ci-local-$name.sha256"
  want=$({ [ ${#files[@]} -eq 0 ] || cat "${files[@]}"; "$venv/bin/python" --version 2>&1; echo "$*"; } | sha256_of)
  if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$want" ]; then
    echo "   deps unchanged: $venv ($name)"
    return 0
  fi
  "$@" || return 1
  echo "$want" > "$stamp"
}

# Create the venv once and (re)install CI Python deps from the same manifest CI uses.
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV" || exit 1
fi
# A failed full install (fallback below) writes no stamp, so the next run tries the full manifest
# again, as before; only a successful full install is skipped.
if ! install_once "$VENV" ci-manifest .github/workflows/requirements.txt -- \
     "$VENV/bin/pip" install --quiet -r .github/workflows/requirements.txt; then
  # The test harness needs the pinned (newer) Python and is only used by pytest, which runs in CI.
  # The Docker-free checks below need just pyyaml, so fall back to those.
  echo "WARN: full CI manifest not installable on $("$VENV/bin/python" --version); installing Docker-free deps only"
  "$VENV/bin/pip" install --quiet pyyaml requests || exit 1
fi
# yamllint comes from the venv, so no system install (brew/apt) is needed locally or in cloud sessions.
install_once "$VENV" yamllint -- "$VENV/bin/pip" install --quiet yamllint || exit 1
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

# ── YAML checks, mirrors yaml-lint.yml (skipped in a targeted run unless --yaml) ─────────────────
if [ "$RUN_YAML" = 1 ]; then
  step "YAML style (fix_yaml_style.py)" style_check
  step "yamllint" "$YAMLLINT" -c .yamllint.yaml .
  step "yamllint on resolved config + dashboards" lint_resolved
  step "Jinja template extraction" extract_templates
  # Plans need Status + Close, packages need a note symlink (doc/KNOWLEDGE.md K-6, K-8).
  step "knowledge layout" "$VENV/bin/python" .github/scripts/check_knowledge_layout.py
fi

# ── In-process suite (tests/ha), as in tests.yaml ────────────────────────────────────────────────
SKIPPED=()

# setup_tests_ha: the one shared setup for every tests/ha call (venv, custom component, pinned
# mosquitto on PATH). Returns 1 when the pinned Python is missing, so the caller records a skip.
setup_tests_ha() {
  local HAPY MQ_FILE MQ_APP MQ_WANT
  HAPY=$(tr -d '[:space:]' < .github/ha-versions/ha-python.txt)
  PY_TEST=$(command -v "python$HAPY" || true)
  if [ -z "$PY_TEST" ]; then
    echo "── In-process tests (tests/ha)"
    echo "   SKIPPED: python$HAPY not found (the Python Home Assistant requires); brew install python@$HAPY"
    return 1
  fi
  # A second venv, same recipe as .venv above: Home Assistant (PHACC) needs its own Python.
  if [ ! -x .venv-test/bin/python ]; then "$PY_TEST" -m venv .venv-test || exit 1; fi
  # (a venv made by `uv venv` has no pip; use uv then)
  if [ -x .venv-test/bin/pip ]; then
    install_once .venv-test requirements requirements_test.txt -- \
      .venv-test/bin/pip install --quiet -r requirements_test.txt || exit 1
  else
    install_once .venv-test requirements requirements_test.txt -- \
      env VIRTUAL_ENV="$PWD/.venv-test" uv pip install --quiet -r requirements_test.txt || exit 1
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
}

# run_tests_ha: the pytest call. Full run: all of tests/ha with -n auto. Targeted run: the pass-through
# args decide the path (an explicit tests/... path replaces the default tests/ha, else everything
# would run) and -n (the user's wins). Default -n: auto for a --package run (whole packages take
# 60-75 s serial vs 18-22 s with workers, measured on 4 cores), 0 for explicit test ids only (a few
# tests: workers only add start-up, 7 s vs 10 s).
run_tests_ha() {
  local paths=(tests/ha) nargs=(-n auto) a
  if [ "$SELECTED" = 1 ]; then
    [ ${#PKG_ARGS[@]} -gt 0 ] || nargs=(-n 0)
    for a in ${PYTEST_EXTRA[@]+"${PYTEST_EXTRA[@]}"}; do
      case $a in
        tests/*) paths=() ;;
        -n|-n[0-9]*|-nauto|--numprocesses|--numprocesses=*) nargs=() ;;
      esac
    done
  fi
  step "In-process tests (tests/ha)" .venv-test/bin/python -m pytest \
    -c tests/ha/pytest.ini --confcutdir tests/ha --rootdir . \
    ${paths[@]+"${paths[@]}"} ${nargs[@]+"${nargs[@]}"} --timeout=60 -q \
    ${PKG_ARGS[@]+"${PKG_ARGS[@]}"} ${PYTEST_EXTRA[@]+"${PYTEST_EXTRA[@]}"}
}

if [ "$RUN_TESTS" = 1 ]; then
  if setup_tests_ha; then run_tests_ha; else SKIPPED+=("tests/ha"); fi
fi

# ── Real-HA layer (tests/e2e), opt-in: needs Docker and takes a few minutes ─────────────────────
if [ "$E2E" = 1 ]; then
  if ! command -v docker >/dev/null; then
    echo "── Real-HA tests (tests/e2e)"; echo "   FAILED: --e2e needs docker"; FAILED+=("tests/e2e")
  else
    # Own venv: its pins (pytest 9.2) differ from the PHACC ones.
    [ -x .venv-e2e/bin/python ] || "${PY_TEST:-$PY}" -m venv .venv-e2e || exit 1
    install_once .venv-e2e requirements tests/e2e/requirements.txt -- \
      .venv-e2e/bin/pip install --quiet -r tests/e2e/requirements.txt || exit 1
    step "Real-HA tests (tests/e2e)" .venv-e2e/bin/python -m pytest \
      -c tests/e2e/pytest.ini --confcutdir tests/e2e --rootdir . tests/e2e \
      -p no:homeassistant --timeout=300 --timeout-method=thread
  fi
elif [ "$SELECTED" = 0 ]; then
  SKIPPED+=("tests/e2e (needs Docker, run with --e2e)")
fi

if [ ${#SKIPPED[@]} -gt 0 ]; then echo; echo "Skipped (NOT checked): ${SKIPPED[*]}"; fi

if [ ${#FAILED[@]} -gt 0 ]; then
  echo; echo "Failed: ${FAILED[*]}"; exit 1
fi
if [ "$SELECTED" = 1 ]; then
  echo; echo "TARGETED RUN – not a full verification; run .github/scripts/ci-local.sh without arguments before pushing"
else
  echo; echo "All local checks passed."
fi
