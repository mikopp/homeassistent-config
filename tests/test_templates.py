"""Jinja2 template validation tests using the live harness HA session.

Replaces the separate validate_templates.py workflow steps. Uses the same HA instance
as the automation tests (session-scoped harness container), so no extra container is
needed. Templates are extracted by .github/scripts/extract_templates.py before pytest
runs; the path is passed via the TEMPLATES_JSON environment variable.

Strict mode (state templates): all entity state is seeded by conftest baseline fixtures
before these tests run, so undefined-variable errors and sentinel outputs are real failures.
Lenient mode (runtime templates): undefined-variable errors are skipped (trigger/wait/etc.
variables are only available inside a live automation run).
"""

import json
import os

import pytest
import requests
from ha_integration_test_harness import HomeAssistant

_TEMPLATES_FILE = os.environ.get("TEMPLATES_JSON", "/tmp/templates.json")
_SENTINELS = {"unknown", "unavailable", "None", "none", ""}


@pytest.fixture(scope="module")
def templates() -> dict:
    """Load the templates JSON produced by extract_templates.py."""
    if not os.path.exists(_TEMPLATES_FILE):
        pytest.skip(
            f"Templates JSON not found at {_TEMPLATES_FILE}. "
            "Run: python3 .github/scripts/extract_templates.py . > /tmp/templates.json"
        )
    with open(_TEMPLATES_FILE) as f:
        return json.load(f)


def _call_template(home_assistant: HomeAssistant, template: str) -> requests.Response:
    return requests.post(
        f"{home_assistant._base_url}/api/template",
        headers={
            "Authorization": f"Bearer {home_assistant._access_token}",
            "Content-Type": "application/json",
        },
        json={"template": template},
        timeout=15,
    )


def _is_undefined_error(message: str) -> bool:
    return "is undefined" in message or "UndefinedError" in message


def test_state_templates_strict(home_assistant: HomeAssistant, templates: dict) -> None:
    """State templates render without errors or sentinel values (strict — state is seeded)."""
    failures = []
    for item in templates["state_templates"]:
        tmpl = item["template"] if isinstance(item, dict) else item
        file_path = item.get("file", "?") if isinstance(item, dict) else "?"
        resp = _call_template(home_assistant, tmpl)
        if resp.status_code != 200:
            try:
                msg = resp.json().get("message", resp.text)
            except Exception:
                msg = resp.text
            failures.append(f"{file_path}: {msg}")
        elif resp.text.strip() in _SENTINELS:
            failures.append(f"{file_path}: sentinel output: {resp.text.strip()!r}")
    assert not failures, "State template failures (strict mode):\n" + "\n".join(failures)


def test_runtime_templates_lenient(home_assistant: HomeAssistant, templates: dict) -> None:
    """Runtime templates have no syntax errors; undefined-var errors are skipped (expected)."""
    failures = []
    for item in templates["runtime_templates"]:
        tmpl = item["template"] if isinstance(item, dict) else item
        file_path = item.get("file", "?") if isinstance(item, dict) else "?"
        resp = _call_template(home_assistant, tmpl)
        if resp.status_code != 200:
            try:
                msg = resp.json().get("message", resp.text)
            except Exception:
                msg = resp.text
            # Undefined-variable errors are expected for runtime-only vars (trigger, wait, etc.)
            if not _is_undefined_error(msg):
                failures.append(f"{file_path}: {msg}")
    assert not failures, "Runtime template failures (lenient mode):\n" + "\n".join(failures)
