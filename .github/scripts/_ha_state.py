"""Shared HA state-seeding helpers.

Imported by seed_state.py (CLI wrapper) and run_automations.py (scenario overlay).
Provides apply_inputs() and apply_states() — thin wrappers around the HA REST API
that dispatch by entity domain and retry on transient failures.
"""

import time

import requests


# ── HTTP helpers ───────────────────────────────────────────────────────────────────────

def _headers(token):
    """Return standard HA API auth headers."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _call_service(ha_url, token, domain, service, data, entity_id, retries):
    """POST to /api/services/<domain>/<service>."""
    url = f"{ha_url}/api/services/{domain}/{service}"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, headers=_headers(token), json=data, timeout=15)
            if resp.status_code in (200, 201):
                return True
            print(f"  WARN [{entity_id}] service call returned {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            print(f"  WARN [{entity_id}] attempt {attempt}/{retries}: {exc}")
        if attempt < retries:
            time.sleep(1)
    return False


def _set_state(ha_url, token, entity_id, state, attributes, retries):
    """POST /api/states/{entity_id} and verify by reading back."""
    url = f"{ha_url}/api/states/{entity_id}"
    payload = {"state": str(state)}
    if attributes:
        payload["attributes"] = attributes

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, headers=_headers(token), json=payload, timeout=15)
            if resp.status_code in (200, 201):
                verify = requests.get(url, headers=_headers(token), timeout=10)
                if verify.status_code == 200:
                    actual = verify.json().get("state")
                    if actual == str(state):
                        return True
                    print(f"  WARN [{entity_id}] wrote '{state}' but read back '{actual}'")
                else:
                    print(f"  WARN [{entity_id}] verify GET returned {verify.status_code}")
            else:
                print(f"  WARN [{entity_id}] POST returned {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            print(f"  WARN [{entity_id}] attempt {attempt}/{retries}: {exc}")
        if attempt < retries:
            time.sleep(1)
    return False


# ── Input seeding — dispatch by domain prefix ──────────────────────────────────────────

def _apply_input(ha_url, token, entity_id, value, retries):
    """Apply a single input_* helper via the appropriate service call."""
    domain = entity_id.split(".")[0]

    if domain == "input_boolean":
        svc = "turn_on" if str(value).lower() in ("on", "true", "1") else "turn_off"
        return _call_service(ha_url, token, "input_boolean", svc,
                             {"entity_id": entity_id}, entity_id, retries)

    if domain == "input_number":
        return _call_service(ha_url, token, "input_number", "set_value",
                             {"entity_id": entity_id, "value": value}, entity_id, retries)

    if domain == "input_select":
        return _call_service(ha_url, token, "input_select", "select_option",
                             {"entity_id": entity_id, "option": str(value)}, entity_id, retries)

    if domain == "input_text":
        return _call_service(ha_url, token, "input_text", "set_value",
                             {"entity_id": entity_id, "value": str(value)}, entity_id, retries)

    if domain == "input_datetime":
        if isinstance(value, dict):
            data = {"entity_id": entity_id, **value}
        else:
            data = {"entity_id": entity_id, "datetime": str(value)}
        return _call_service(ha_url, token, "input_datetime", "set_datetime",
                             data, entity_id, retries)

    print(f"  WARN [{entity_id}] unknown input domain '{domain}' — skipping")
    return False


# ── Public API ─────────────────────────────────────────────────────────────────────────

def apply_inputs(ha_url, token, mapping, retries=3):
    """Apply a {entity_id: value} dict of input helpers via service calls.

    Returns a list of entity IDs that failed.
    """
    failures = []
    for entity_id, value in (mapping or {}).items():
        ok = _apply_input(ha_url, token, entity_id, value, retries)
        status = "✓" if ok else "✗"
        print(f"  {status} {entity_id} = {value!r}")
        if not ok:
            failures.append(entity_id)
    return failures


def apply_states(ha_url, token, mapping, retries=3):
    """Apply a {entity_id: spec} dict of stub states via POST /api/states.

    spec may be {"state": "x", "attributes": {...}} or just {"state": "x"}.
    Returns a list of entity IDs that failed.
    """
    failures = []
    for entity_id, spec in (mapping or {}).items():
        if isinstance(spec, dict):
            state_val = spec.get("state", "unknown")
            attributes = spec.get("attributes")
        else:
            state_val = str(spec)
            attributes = None
        ok = _set_state(ha_url, token, entity_id, state_val, attributes, retries)
        status = "✓" if ok else "✗"
        print(f"  {status} {entity_id} = {state_val!r}")
        if not ok:
            failures.append(entity_id)
    return failures
