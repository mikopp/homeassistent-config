"""Keep both test layers on one Home Assistant release.

The in-process layer (tests/ha) gets Home Assistant from the exact pin inside pytest-homeassistant
(home-assistant/core, requirements_test.txt), which is versioned like Home Assistant: its release
number is the HA release it pins. The Docker layer and the CI config check get HA from the image
tag in the FROM line of .github/ha-versions/ha/Dockerfile. Dependabot bumps the image and the test
package in one PR (multi-ecosystem group in .github/dependabot.yml); these tests fail until the
full versions (patch included) match again.

They also check that the integration requirements the package does not install (holidays, cronsim,
sqlparse, aiohasupervisor) equal the pins in HA's own manifests, that the Python running the tests is one HA
accepts, and that the Python CI sets up (.github/ha-versions/ha-python.txt) is exactly HA's.

The MQTT broker is pinned like Home Assistant: .github/ha-versions/mosquitto/Dockerfile names the
official Home Assistant Mosquitto app, and the mosquitto the tests start (the first one on PATH,
what tests/ha/conftest.py runs) must be the version that app ships.

Plain sync tests: no fixture starts Home Assistant.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import homeassistant
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION, REQUIRED_PYTHON_VER

DOCKERFILE = Path(__file__).resolve().parents[2] / ".github" / "ha-versions" / "ha" / "Dockerfile"

VERSIONS = DOCKERFILE.parents[1]  # .github/ha-versions
MOSQUITTO_DOCKERFILE = VERSIONS / "mosquitto" / "Dockerfile"
HA_PYTHON = VERSIONS / "ha-python.txt"

# Installed HA's integrations folder; manifests are read as files, never imported (importing an
# integration would need its own requirements).
COMPONENTS = Path(homeassistant.__file__).parent / "components"

# (integration, package) pairs whose package requirements_test.txt installs by hand.
INTEGRATION_REQUIREMENTS = [("workday", "holidays"), ("utility_meter", "cronsim"), ("sql", "sqlparse"), ("hassio", "aiohasupervisor")]


# Test requirements file; read as text so the pin line itself is checked, not only the installed one.
REQUIREMENTS = DOCKERFILE.parents[3] / "requirements_test.txt"


def test_in_process_ha_matches_docker_image() -> None:
    """The Dockerfile image tag is the installed Home Assistant, patch release included."""
    # Only a pinned X.Y.Z tag matches; latest/stable/beta/dev do not.
    match = re.search(r"^FROM\s+\S+:(\d+\.\d+\.\d+)\s*$", DOCKERFILE.read_text(), re.M)
    assert match, (
        f"{DOCKERFILE} must pin a Home Assistant release tag (YYYY.M.P), "
        "not latest/stable/beta/dev"
    )
    assert match[1] == HA_VERSION, (
        f"Docker image is Home Assistant {match[1]}, but the in-process tests run {HA_VERSION}: "
        "bump both together (requirements_test.txt and .github/ha-versions/ha/Dockerfile)"
    )


def test_test_package_pin_is_the_installed_version() -> None:
    """requirements_test.txt pins pytest-homeassistant, and the installed one is that version.

    The package depends on `homeassistant==<its own version>`, so the installed HA cannot differ
    from the package; what can differ is the pin line (an edited file with a stale venv, or the
    reverse) and the package itself (the obsolete pytest-homeassistant-custom-component must not
    be installed next to it: overlapping fixtures).
    """
    pin = re.search(r"^pytest-homeassistant==(\S+)\s*$", REQUIREMENTS.read_text(), re.M)
    assert pin, f"{REQUIREMENTS.name} must pin pytest-homeassistant==<Home Assistant release>"
    assert pin[1] == version("pytest-homeassistant"), (
        f"{REQUIREMENTS.name} pins pytest-homeassistant=={pin[1]}, installed is "
        f"{version('pytest-homeassistant')}: reinstall requirements_test.txt"
    )
    assert pin[1] == HA_VERSION, (
        f"{REQUIREMENTS.name} pins pytest-homeassistant=={pin[1]}, Home Assistant is {HA_VERSION}"
    )
    try:
        old = version("pytest-homeassistant-custom-component")
    except PackageNotFoundError:
        return
    raise AssertionError(
        f"pytest-homeassistant-custom-component {old} is installed next to pytest-homeassistant: "
        "uninstall it (recreate the venv)"
    )


def manifest_pin(component: str, package: str) -> str:
    """Return the `package==X` version that HA's manifest for `component` requires."""
    manifest = COMPONENTS / component / "manifest.json"
    wanted = [
        r.partition("==")[2]
        for r in json.loads(manifest.read_text())["requirements"]
        if r.startswith(f"{package}==")
    ]
    assert len(wanted) == 1, f"Home Assistant's {component} manifest no longer pins {package}"
    return wanted[0]


def test_integration_requirements_match_home_assistant() -> None:
    """Hand-installed integration requirements equal HA's manifest pins."""
    for component, package in INTEGRATION_REQUIREMENTS:
        wanted = manifest_pin(component, package)
        assert version(package) == wanted, (
            f"Home Assistant's {component} needs {package}=={wanted}, tests run "
            f"{version(package)}: set {package} in requirements_test.txt to {wanted}"
        )


def test_python_matches_home_assistant() -> None:
    """The test interpreter is at least the Python version HA requires."""
    assert sys.version_info[:3] >= REQUIRED_PYTHON_VER, (
        f"Home Assistant {MAJOR_VERSION}.{MINOR_VERSION} requires Python "
        f"{'.'.join(map(str, REQUIRED_PYTHON_VER))}, tests run {sys.version.split()[0]}"
    )


def test_ci_python_is_the_python_home_assistant_requires() -> None:
    """CI sets up the Python in ha-python.txt; it must be HA's `major.minor`.

    That file is not bumped by Dependabot (the tooling pin in ha-versions/python is, and runs
    ahead of HA): it follows Home Assistant, which supports one Python minor at a time.
    """
    wanted = ".".join(map(str, REQUIRED_PYTHON_VER[:2]))
    assert HA_PYTHON.read_text().strip() == wanted, (
        f"Home Assistant {MAJOR_VERSION}.{MINOR_VERSION} requires Python {wanted}: "
        f"set {HA_PYTHON.relative_to(HA_PYTHON.parents[2])} to {wanted}"
    )


def test_mosquitto_is_the_version_of_the_pinned_ha_app() -> None:
    """The mosquitto on PATH is the one the pinned Home Assistant Mosquitto app ships."""
    text = MOSQUITTO_DOCKERFILE.read_text()
    image = re.search(r"^FROM\s+(\S+):(\d+\.\d+\.\d+)\s*$", text, re.M)
    assert image, f"{MOSQUITTO_DOCKERFILE} must pin an app release tag (X.Y.Z)"
    app = image[2]
    # The app version -> mosquitto version map, recorded next to the pin (Dependabot only bumps
    # the FROM line, so a new app version has no entry until someone reads what it ships).
    shipped = dict(re.findall(r"^#\s*mosquitto-in-app:\s*(\S+)\s*=\s*(\S+)\s*$", text, re.M))
    assert app in shipped, (
        f"{MOSQUITTO_DOCKERFILE.name} pins app {app} but records no mosquitto version for it: "
        f"add the line `# mosquitto-in-app: {app} = <version>` (run "
        ".github/scripts/install-mosquitto.sh, then `mosquitto -h`)"
    )
    wanted = shipped[app]

    binary = shutil.which("mosquitto")
    assert binary, (
        "mosquitto not found on PATH: run .github/scripts/install-mosquitto.sh and put "
        f".cache/mosquitto/bin on PATH (or install mosquitto {wanted} yourself)"
    )
    # `-h` prints the version and exits; a timeout bounds a broker that would start instead.
    out = subprocess.run(
        [binary, "-h"], capture_output=True, text=True, timeout=10, check=False
    )
    found = re.search(r"^mosquitto version (\S+)", out.stdout + out.stderr, re.M)
    assert found, f"cannot read the version from `{binary} -h`: {out.stdout!r} {out.stderr!r}"
    assert found[1] == wanted, (
        f"the tests start mosquitto {found[1]} ({binary}), but the pinned Home Assistant "
        f"Mosquitto app {app} ships {wanted}: run .github/scripts/install-mosquitto.sh and put "
        ".cache/mosquitto/bin first on PATH (CI does this); on macOS install that version "
        "with brew"
    )
