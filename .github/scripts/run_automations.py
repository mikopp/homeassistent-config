#!/usr/bin/env python3
"""Run all HA automations under every test scenario and assert no trace errors.

This script is automation-agnostic: it discovers automations via GET /api/states,
iterates over scenarios defined in tests/scenarios.yaml, and checks
GET /api/config/automation/trace/<config_id> for error nodes after each trigger.

Usage:
  HA_TOKEN=<token> python run_automations.py \
    --defaults tests/state_defaults.yaml \
    --scenarios tests/scenarios.yaml \
    [--ha-url http://localhost:8123]

Exit codes:
  0  All scenarios passed (no trace errors, no new HA error-log entries)
  1  One or more scenarios produced trace errors or log errors
"""

import argparse
import json
import os
import sys
import time

import requests
import yaml

sys.path.insert(0, os.path.dirname(__file__))
from _ha_state import apply_inputs, apply_states


# ── HTTP helpers ───────────────────────────────────────────────────────────────────────

def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(ha_url, token, path, timeout=15):
    resp = requests.get(f"{ha_url}{path}", headers=_headers(token), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _post(ha_url, token, path, data=None, timeout=15):
    resp = requests.post(
        f"{ha_url}{path}",
        headers=_headers(token),
        json=data or {},
        timeout=timeout,
    )
    return resp


# ── Automation discovery ───────────────────────────────────────────────────────────────

def discover_automations(ha_url, token):
    """Return list of {entity_id, config_id, friendly_name} for all automations."""
    states = _get(ha_url, token, "/api/states")
    automations = []
    for s in states:
        eid = s.get("entity_id", "")
        if not eid.startswith("automation."):
            continue
        config_id = s.get("attributes", {}).get("id") or eid.split(".", 1)[1]
        name = s.get("attributes", {}).get("friendly_name", eid)
        automations.append({"entity_id": eid, "config_id": config_id, "name": name})
    return automations


# ── Trace inspection ───────────────────────────────────────────────────────────────────

def _trace_has_error(trace):
    """Return the first error message found in a trace dict, or None."""
    # trace["trace"] is a dict of path → list of node dicts
    for nodes in trace.get("trace", {}).values():
        for node in nodes:
            err = node.get("error")
            if err:
                return str(err)
    return None


def get_latest_trace(ha_url, token, config_id):
    """Return the most recent trace for an automation, or None if none exist."""
    try:
        traces = _get(ha_url, token, f"/api/config/automation/trace/{config_id}")
    except requests.HTTPError:
        return None
    if not traces:
        return None
    # Traces are returned newest-first
    return traces[0] if isinstance(traces, list) else None


def get_trace_detail(ha_url, token, config_id, run_id):
    """Fetch the full trace (with node-level detail) for a specific run."""
    try:
        return _get(ha_url, token, f"/api/config/automation/trace/{config_id}/{run_id}")
    except requests.HTTPError:
        return None


# ── Error log snapshot ─────────────────────────────────────────────────────────────────

def get_error_log_lines(ha_url, token):
    """Return the current HA error log as a set of lines."""
    try:
        resp = requests.get(
            f"{ha_url}/api/error/all",
            headers=_headers(token),
            timeout=15,
        )
        if resp.status_code == 200:
            return set(resp.text.splitlines())
    except requests.RequestException:
        pass
    return set()


# ── Scenario application ───────────────────────────────────────────────────────────────

def apply_scenario(ha_url, token, defaults, scenario, retries=3):
    """Re-seed baseline then apply scenario overrides. Returns list of failed entity IDs."""
    failures = []

    # Re-apply full baseline for a clean slate
    failures += apply_inputs(ha_url, token, defaults.get("inputs") or {}, retries=retries)
    failures += apply_states(ha_url, token, defaults.get("states") or {}, retries=retries)

    # Apply scenario-specific overrides on top
    overrides = scenario.get("overrides") or {}
    failures += apply_inputs(ha_url, token, overrides.get("inputs") or {}, retries=retries)
    failures += apply_states(ha_url, token, overrides.get("states") or {}, retries=retries)

    return failures


# ── Automation trigger + trace check ──────────────────────────────────────────────────

def trigger_and_check(ha_url, token, automation, wait_s=3):
    """Trigger an automation and check its latest trace for errors.

    Returns (ok: bool, error_msg: str | None).
    """
    entity_id = automation["entity_id"]
    config_id = automation["config_id"]

    # Snapshot the run_id before triggering so we can find the new trace
    latest_before = get_latest_trace(ha_url, token, config_id)
    run_id_before = (latest_before or {}).get("run_id")

    # Trigger with conditions enforced (skip_condition=False) — the scenario state
    # should satisfy whatever conditions the automation has. If it doesn't, the
    # automation simply won't run, which is also a valid outcome.
    _post(
        ha_url, token,
        "/api/services/automation/trigger",
        {"entity_id": entity_id, "skip_condition": False},
    )

    # Wait briefly for the trace to be written
    time.sleep(wait_s)

    latest_after = get_latest_trace(ha_url, token, config_id)
    if latest_after is None or latest_after.get("run_id") == run_id_before:
        # Automation did not run (conditions not met for this scenario) — that is OK
        return True, None

    run_id = latest_after["run_id"]
    detail = get_trace_detail(ha_url, token, config_id, run_id)
    if detail is None:
        return True, None

    error = _trace_has_error(detail)
    if error:
        return False, error
    return True, None


# ── Main ───────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run all automations under test scenarios.")
    parser.add_argument("--defaults", required=True, help="Path to state_defaults.yaml")
    parser.add_argument("--scenarios", required=True, help="Path to scenarios.yaml")
    parser.add_argument("--ha-url", default="http://localhost:8123", help="HA base URL")
    parser.add_argument("--retries", type=int, default=3, help="Retry count for seeding")
    args = parser.parse_args()

    token = os.environ.get("HA_TOKEN", "")
    if not token:
        print("ERROR: HA_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    with open(args.defaults, encoding="utf-8") as fh:
        defaults = yaml.safe_load(fh)

    with open(args.scenarios, encoding="utf-8") as fh:
        scenarios_doc = yaml.safe_load(fh)
    scenarios = scenarios_doc.get("scenarios", [])

    automations = discover_automations(args.ha_url, token)
    print(f"Discovered {len(automations)} automation(s).")
    print(f"Running {len(scenarios)} scenario(s).\n")

    all_failures = []  # list of {"scenario", "automation", "error"}

    for scenario in scenarios:
        name = scenario.get("name", "unnamed")
        print(f"── Scenario: {name} {'─' * max(0, 50 - len(name))}")

        # Seed state for this scenario
        seed_failures = apply_scenario(args.ha_url, token, defaults, scenario, args.retries)
        if seed_failures:
            print(f"  WARN: failed to seed {len(seed_failures)} entity/entities for scenario '{name}'")

        # Snapshot error log before running automations
        log_before = get_error_log_lines(args.ha_url, token)

        # Trigger every automation and check traces
        for auto in automations:
            ok, error = trigger_and_check(args.ha_url, token, auto)
            if not ok:
                print(f"  ✗ {auto['name']} — trace error: {error}")
                all_failures.append({
                    "scenario": name,
                    "automation": auto["name"],
                    "error": error,
                })
            else:
                print(f"  ✓ {auto['name']}")

        # Check for new HA error-log entries produced during this scenario
        log_after = get_error_log_lines(args.ha_url, token)
        new_errors = log_after - log_before
        for line in sorted(new_errors):
            if "ERROR" in line:
                print(f"  ✗ New HA error log entry: {line}")
                all_failures.append({
                    "scenario": name,
                    "automation": "(HA error log)",
                    "error": line,
                })

        print()

    # ── Summary ───────────────────────────────────────────────────────────────────────
    total_runs = len(scenarios) * len(automations)
    print(f"{'=' * 60}")
    print(f"Ran {total_runs} automation trigger(s) across {len(scenarios)} scenario(s).")
    if all_failures:
        print(f"FAILED: {len(all_failures)} error(s)\n")
        for idx, f in enumerate(all_failures, 1):
            print(f"  [{idx}] Scenario:   {f['scenario']}")
            print(f"       Automation: {f['automation']}")
            print(f"       Error:      {f['error']}")
            print()

        # GitHub Actions annotations
        for f in all_failures:
            msg = f["error"].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::error title=Automation trace error [{f['scenario']}]::{f['automation']} — {msg}")

        sys.exit(1)

    print("All scenarios passed.")


if __name__ == "__main__":
    main()
