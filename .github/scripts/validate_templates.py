#!/usr/bin/env python3
"""Validate Jinja2 templates against a running Home Assistant instance.

Usage: python validate_templates.py --templates <file.json> [--ha-url <url>] [--strict]
  HA_TOKEN environment variable must be set to a valid long-lived access token.

Exit codes:
  0  All templates valid (or only had expected undefined-variable errors)
  1  One or more templates have real errors (syntax, unknown filters, etc.)
"""

import argparse
import json
import os
import sys

import requests


# Result bodies that indicate the template rendered to a sentinel non-value.
# In strict mode (state seeded) these are treated as errors.
_SENTINEL_OUTPUTS = {"unknown", "unavailable", "None", "none", ""}


def _is_undefined_error(message):
    """Return True when the error is a missing runtime variable (expected)."""
    return "is undefined" in message or "UndefinedError" in message


def validate_template(ha_url, token, template, strict=False):
    """Call POST /api/template. Returns (ok, skip, error_message).

    ok    — template rendered without errors
    skip  — template uses runtime-only vars; result is ambiguous (lenient mode only)
    error — otherwise
    """
    try:
        resp = requests.post(
            f"{ha_url}/api/template",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"template": template},
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, False, str(exc)

    if resp.status_code == 200:
        # In strict mode a sentinel output means the template evaluated to an
        # undefined/unavailable value even though HA returned HTTP 200.
        if strict and resp.text.strip() in _SENTINEL_OUTPUTS:
            return False, False, f"rendered to sentinel value: {resp.text.strip()!r}"
        return True, False, None

    # Parse the error body
    try:
        message = resp.json().get("message", resp.text)
    except Exception:
        message = resp.text

    if _is_undefined_error(message):
        if strict:
            # State was seeded — undefined vars are real errors, not runtime skips
            return False, False, message
        # Template syntax is fine; it just uses a runtime variable
        return False, True, message

    return False, False, message


def main():
    parser = argparse.ArgumentParser(description="Validate HA Jinja2 templates via REST API.")
    parser.add_argument("--templates", required=True, help="Path to JSON file with template strings.")
    parser.add_argument("--ha-url", default="http://localhost:8123", help="Base URL of the HA instance.")
    # In strict mode, undefined-variable errors are failures (not skips) because
    # state has been seeded. Sentinel outputs (unknown/unavailable/None) also fail.
    parser.add_argument("--strict", action="store_true", default=False,
                        help="Fail on undefined-variable errors and sentinel outputs (use after seeding state).")
    args = parser.parse_args()

    token = os.environ.get("HA_TOKEN", "")
    if not token:
        print("ERROR: HA_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    with open(args.templates, encoding="utf-8") as fh:
        templates = json.load(fh)

    total = len(templates)
    mode = "strict" if args.strict else "lenient"
    print(f"Validating {total} template(s) against {args.ha_url} [{mode} mode] …")

    failures = []
    skipped = 0

    for item in templates:
        tmpl = item["template"] if isinstance(item, dict) else item
        file_path = item.get("file", "unknown") if isinstance(item, dict) else "unknown"
        ok, skip, error = validate_template(args.ha_url, token, tmpl, strict=args.strict)
        if ok:
            pass
        elif skip:
            skipped += 1
        else:
            failures.append({"template": tmpl, "file": file_path, "error": error})

    valid = total - len(failures) - skipped
    print(f"  ✓ valid:   {valid}")
    if not args.strict:
        print(f"  ~ skipped (runtime-only vars): {skipped}")
    print(f"  ✗ invalid: {len(failures)}")

    if failures:
        print(f"\n{'='*60}")
        print(f"FAILED: {len(failures)} invalid template(s)\n")
        for idx, item in enumerate(failures, 1):
            file_path = item["file"]
            error = item["error"]
            preview = item["template"].replace("\n", " ").strip()
            if len(preview) > 120:
                preview = preview[:117] + "..."

            # GitHub Actions annotation — shows as an inline file annotation in the PR
            # Property values (before ::) need : and , escaped; the message after :: only needs % \r \n.
            def _esc_msg(s):
                return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::error file={file_path},title=Invalid Jinja2 template::{_esc_msg(preview)} — {_esc_msg(error)}")

            # Human-readable summary
            print(f"  [{idx}] File:     {file_path}")
            print(f"       Template: {preview!r}")
            print(f"       Error:    {error}")
            print()
        sys.exit(1)

    print("\nAll templates passed validation.")


if __name__ == "__main__":
    main()
