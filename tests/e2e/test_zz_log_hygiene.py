"""Needs a real HA because: only the real container log shows what Home Assistant itself thinks
of this config over a whole session, including a real restart (`runtime-logs`): errors,
tracebacks and deprecation warnings that no in-process fixture reports the same way (the
in-process `log_guard` sees one test's HA; this sees the config boot with default_config, the
frontend, HACS code and a real MQTT connection).

Named `zz` so it runs last. A deprecation shows up here months before Home Assistant removes the
API, which is the point.

What is judged: the log from the clean boot on (the bootstrap boot of a fresh install is excluded,
see `session` in conftest.py) through every restart the other tests made. The container logs at
WARNING and above (HA's default), so INFO lines are not there.

The rule is "everything fails except what is listed", so a new error source is a failure until
somebody decides it is noise. Two lists, each entry with a regex, the reason, and (for noise that
only follows from another failure) the condition under which it is allowed:
- `EXTERNAL_NOISE`: errors from things outside this config that a CI runner or sandbox cannot
  reach or controls;
- `KNOWN_CONFIG_BUGS`: real findings in this config that are open; delete the entry with the fix.
"""

from __future__ import annotations

import re
from typing import NamedTuple

import pytest

pytestmark = pytest.mark.needs_real_ha("runtime-logs")

LINE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ (?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL) "
    r"\((?P<thread>[^)]*)\) \[(?P<logger>[^\]]*)\] (?P<message>.*)$"
)
ANSI = re.compile(r"\x1b\[[0-9;]*m")


class Allowed(NamedTuple):
    pattern: re.Pattern[str]  # searched in "<logger> <message>" of the record
    reason: str
    only_if_log_has: re.Pattern[str] | None = None  # the cause that must also be in the log


# Noise from outside this config. Nothing here may hide an error of our own YAML.
EXTERNAL_NOISE = [
    Allowed(
        re.compile(r"^metno "),
        "Met.no (the default weather entity onboarding creates) cannot be reached: a runner or "
        "sandbox without internet access to api.met.no",
    ),
    Allowed(
        re.compile(r"^homeassistant\.components\.homeassistant_alerts"),
        "alerts.home-assistant.io is fetched by default_config; unreachable without internet",
    ),
    # Radio Browser is another entry onboarding creates; it needs the internet. While its setup
    # retries, a stop (every restart) cancels it and HA logs that as ERROR. Timing decides whether
    # a run sees it, so it is allowed only together with the unreachable API that causes it.
    Allowed(
        re.compile(r"^homeassistant\.components\.radio_browser Setup of config entry .* cancelled"),
        "Radio Browser (created by onboarding) cannot reach its API; a restart cancels its retry",
        only_if_log_has=re.compile(r"Cannot connect to host [\w.]*radio-browser\.info"),
    ),
    # Follow-ups of an unreachable Met.no: weather.home is then missing, so the forecast call of
    # packages/heating_cooling_indicator.yaml finds no entity. Allowed only together with that cause.
    Allowed(
        re.compile(r"trigger_update_coordinator.*did not match any entities"),
        "weather.get_forecasts has no weather entity while Met.no is unreachable",
        only_if_log_has=re.compile(r"\[metno\] Access to"),
    ),
    Allowed(
        re.compile(r"^homeassistant Error doing job: Task exception was never retrieved"),
        "the asyncio companion of the line above (same cause)",
        only_if_log_has=re.compile(r"\[metno\] Access to"),
    ),
]

# Open findings in this config, logged on every run. Remove an entry when its fix lands.
KNOWN_CONFIG_BUGS = [
    Allowed(
        re.compile(
            r"homeassistant\.components\.template\.validators Received invalid sensor state: "
            r"unknown for entity sensor\.victron_(solar_yield_dc|ac_pv_energy)_baseline_kwh"
        ),
        "#147: the baseline sensors render the string 'unknown' into a numeric energy sensor "
        "before the Venus counters arrive (fix proposed: render none)",
    ),
]


def _records(log: str) -> list[dict]:
    """Log records with their continuation lines (tracebacks) attached."""
    records: list[dict] = []
    for line in ANSI.sub("", log).splitlines():
        match = LINE.match(line)
        if match:
            records.append({**match.groupdict(), "extra": []})
        elif records:
            records[-1]["extra"].append(line)
    return records


def _allowed(record: dict, log: str) -> bool:
    text = f"{record['logger']} {record['message']}"
    return any(
        a.pattern.search(text) and (a.only_if_log_has is None or a.only_if_log_has.search(log))
        for a in (*EXTERNAL_NOISE, *KNOWN_CONFIG_BUGS)
    )


def test_no_errors_or_deprecations_in_the_session_log(ha_log):
    log = ANSI.sub("", ha_log())
    records = _records(log)

    # Proof that this is the right log: the staged custom component is announced once per boot,
    # and the session had at least two boots after the bootstrap (the clean boot, a restart).
    boots = sum("climate_template" in r["message"] and r["logger"] == "homeassistant.loader" for r in records)
    assert boots >= 2, f"expected the log of at least two boots, found {boots} ({len(records)} records)"

    problems = []
    for record in records:
        level, message = record["level"], record["message"]
        if _allowed(record, log):
            continue
        if "deprecated" in message.lower() or any("deprecated" in x.lower() for x in record["extra"]):
            problems.append(f"{level} deprecation [{record['logger']}] {message}")
        elif level in ("ERROR", "CRITICAL"):
            problems.append(f"{level} [{record['logger']}] {message}")
        elif any("Traceback" in x for x in record["extra"]):
            problems.append(f"traceback after: [{record['logger']}] {message}")
    assert not problems, "Home Assistant logged problems:\n" + "\n".join(problems)
