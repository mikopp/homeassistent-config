#!/usr/bin/env python3
"""Seed a running Home Assistant instance with known-good state for CI template tests.

Reads tests/state_defaults.yaml (or any file passed via --defaults) and applies:
  - inputs:  via service calls (input_boolean/number/select/text/datetime)
  - states:  via POST /api/states/{entity_id}

Usage:
  HA_TOKEN=<token> python seed_state.py --defaults tests/state_defaults.yaml [--ha-url http://localhost:8123] [--retries 3]

Exit codes:
  0  All entities seeded successfully
  1  One or more entities failed to seed
"""

import argparse
import os
import sys

import yaml

# _ha_state lives alongside this script in the same .github/scripts/ directory.
sys.path.insert(0, os.path.dirname(__file__))
from _ha_state import apply_inputs, apply_states


def main():
    parser = argparse.ArgumentParser(description="Seed HA state for CI tests.")
    parser.add_argument("--defaults", required=True, help="Path to state_defaults.yaml")
    parser.add_argument("--ha-url", default="http://localhost:8123", help="HA base URL")
    parser.add_argument("--retries", type=int, default=3, help="Retry count per entity")
    args = parser.parse_args()

    token = os.environ.get("HA_TOKEN", "")
    if not token:
        print("ERROR: HA_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    with open(args.defaults, encoding="utf-8") as fh:
        defaults = yaml.safe_load(fh)

    failures = []

    inputs = defaults.get("inputs") or {}
    if inputs:
        print(f"Seeding {len(inputs)} input helper(s)…")
        failures += apply_inputs(args.ha_url, token, inputs, retries=args.retries)

    states = defaults.get("states") or {}
    if states:
        print(f"\nSeeding {len(states)} stub state(s)…")
        failures += apply_states(args.ha_url, token, states, retries=args.retries)

    total = len(inputs) + len(states)
    print(f"\nSeeded {total - len(failures)}/{total} entities successfully.")
    if failures:
        print(f"\nFAILED to seed {len(failures)} entity/entities:", file=sys.stderr)
        for eid in failures:
            print(f"  - {eid}", file=sys.stderr)
        sys.exit(1)

    print("State seeding complete.")


if __name__ == "__main__":
    main()
