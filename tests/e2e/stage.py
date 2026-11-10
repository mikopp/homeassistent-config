"""Stage this repo's Home Assistant config as a throw-away /config for the e2e layer.

    python -m tests.e2e.stage <dir>                 # stage into <dir> (emptied first)
    python -m tests.e2e.stage <dir> --check-config  # stage, then run HA's check_config on it

One staging, two users: the pytest fixtures (tests/e2e/conftest.py) boot a container on the
result, and test_check_config.py runs `--check-config` on it (the CI e2e job runs both), so both
look at exactly the same configuration.

What the staged copy is:
- the repo's real `configuration.yaml` (default_config, frontend, lovelace dashboards, recorder,
  rest_command, packages), plus the home location HA needs, inserted into a COPY of the file
  (the repo file stays untouched; this is what CI used to do with `sed -i`);
- `fakesecrets.yaml` as `secrets.yaml`;
- the YAML the config includes (`automations.yaml`, `scripts.yaml`, `scenes.yaml`, `packages/`,
  `dashboards/`, `blueprints/`, `custom_templates/`) and an empty `themes/` (the frontend
  includes that directory);
- the custom components from `tests/custom_components.yaml` (the HACS `climate_template`),
  installed by `.github/scripts/install_custom_components.py` (the repo's `custom_components/` if
  present, else downloaded from GitHub; CI runs the same script once before the tests).

Not staged on purpose: `tests/custom_components.yaml` `ha_yaml_config` (the `workday` YAML
platform). Home Assistant at the pinned version rejects it ("does not support platform setup");
the e2e fixtures create workday as a config entry through the real config flow instead, which is
how production has it.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / ".github" / "ha-versions" / "ha" / "Dockerfile"


def _load_installer():
    """Import .github/scripts/install_custom_components.py (not a package) by path.

    The one implementation of the custom-component install: CI steps, ci-local.sh and this
    staging all use it, none has a copy.
    """
    path = ROOT / ".github" / "scripts" / "install_custom_components.py"
    spec = importlib.util.spec_from_file_location("install_custom_components", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Production location (CI used the same coordinates via sed). Inserted into the staged
# configuration.yaml; without a location HA starts with the default "Home" at 0/0.
LOCATION = (
    "  latitude: 48.3069\n"
    "  longitude: 14.2858\n"
    "  elevation: 266\n"
    "  time_zone: Europe/Vienna\n"
)

# Top-level files and directories the config includes.
FILES = ("automations.yaml", "scripts.yaml", "scenes.yaml")
DIRECTORIES = ("packages", "dashboards", "blueprints", "custom_templates")

# Output of check_config that means the config is broken. The same patterns the old CI step
# grepped for; "ERROR" covers the logged setup failures.
CHECK_CONFIG_FAILURE = ("invalid config", "invalid slug", "setup of package", "error")


def image_from_dockerfile() -> str:
    """The pinned HA image: the `FROM` line of .github/ha-versions/ha/Dockerfile.

    Read from the file every time (Dependabot bumps it); never `:stable`.
    """
    for line in DOCKERFILE.read_text().splitlines():
        if line.startswith("FROM "):
            return line.split()[1]
    raise RuntimeError(f"no FROM line in {DOCKERFILE}")


def stage(target: Path) -> Path:
    """Build the staged config in `target` (emptied first) and return it."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in FILES:
        shutil.copy(ROOT / name, target / name)
    for name in DIRECTORIES:
        shutil.copytree(ROOT / name, target / name, ignore=shutil.ignore_patterns("__pycache__"))
    (target / "themes").mkdir()
    shutil.copy(ROOT / "fakesecrets.yaml", target / "secrets.yaml")

    # The location goes right under the existing `homeassistant:` key of the copy.
    lines = (ROOT / "configuration.yaml").read_text().splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.startswith("homeassistant:"))
    lines.insert(index + 1, LOCATION)
    (target / "configuration.yaml").write_text("".join(lines))

    # Local checkout copy if there is one, else the download (ref honoured): one implementation.
    _load_installer().install(target, ROOT)
    return target


def check_config(config_dir: Path, image: str | None = None) -> tuple[bool, str]:
    """Run HA's `check_config` script on `config_dir` in a throw-away container.

    Returns (ok, output). The directory is mounted read-write because HA writes its log and
    `.storage` into it; pass a staged copy, never the repo. A timeout bounds a wedged container.
    """
    image = image or image_from_dockerfile()
    result = subprocess.run(
        [
            "docker", "run", "--rm", "-v", f"{config_dir}:/config", image,
            "python", "-m", "homeassistant", "--config", "/config", "--script", "check_config",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = result.stdout + result.stderr
    broken = result.returncode != 0 or any(
        pattern in output.lower() for pattern in CHECK_CONFIG_FAILURE
    )
    return not broken, output


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1 or set(sys.argv[1:]) - {args[0], "--check-config"}:
        sys.exit(__doc__)
    staged = stage(Path(args[0]).resolve())
    print(staged)
    if "--check-config" in sys.argv:
        ok, text = check_config(staged)
        print(text)
        sys.exit(0 if ok else 1)
