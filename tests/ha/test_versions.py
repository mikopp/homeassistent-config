"""Keep both test layers on one Home Assistant release.

The in-process layer (tests/ha) gets Home Assistant from the exact pin inside
pytest-homeassistant-custom-component (PHACC, requirements_test.txt); the Docker layer and the CI
config check get it from the image tag in the FROM line of .github/ha-versions/ha/Dockerfile.
Dependabot bumps the image and PHACC in separate PRs, so these tests fail until their year.month
match again. Patch releases may differ.

They also check that the integration requirements PHACC does not install (holidays, cronsim)
equal the pins in HA's own manifests, and that the Python running the tests is one HA accepts.

Plain sync tests: no fixture starts Home Assistant.
"""

from __future__ import annotations

import json
import re
import sys
from importlib.metadata import version
from pathlib import Path

import homeassistant
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION, REQUIRED_PYTHON_VER

DOCKERFILE = Path(__file__).resolve().parents[2] / ".github" / "ha-versions" / "ha" / "Dockerfile"

# Installed HA's integrations folder; manifests are read as files, never imported (importing an
# integration would need its own requirements).
COMPONENTS = Path(homeassistant.__file__).parent / "components"

# (integration, package) pairs whose package requirements_test.txt installs by hand.
INTEGRATION_REQUIREMENTS = [("workday", "holidays"), ("utility_meter", "cronsim")]


def test_in_process_ha_matches_docker_image() -> None:
    """The Dockerfile image tag and PHACC's HA share the same year.month."""
    # Only a pinned X.Y.Z tag matches; latest/stable/beta/dev do not.
    match = re.search(r"^FROM\s+\S+:(\d+)\.(\d+)\.\d+\s*$", DOCKERFILE.read_text(), re.M)
    assert match, (
        f"{DOCKERFILE} must pin a Home Assistant release tag (YYYY.M.P), "
        "not latest/stable/beta/dev"
    )
    image = (int(match[1]), int(match[2]))
    assert image == (MAJOR_VERSION, MINOR_VERSION), (
        f"Docker image is Home Assistant {image[0]}.{image[1]}, but "
        f"pytest-homeassistant-custom-component runs {MAJOR_VERSION}.{MINOR_VERSION}: "
        "bump both together (requirements_test.txt and .github/ha-versions/ha/Dockerfile)"
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
