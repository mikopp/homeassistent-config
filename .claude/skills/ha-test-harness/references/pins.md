# Pins and guards (`tests/ha/test_versions.py`)

Part of the `ha-test-harness` skill; grades as there (CONFIRMED unless marked).

- `pytest-homeassistant` (home-assistant/core `packages/pytest-homeassistant`) is versioned like HA and pins it exactly:
  its version must equal the Dockerfile `FROM` tag, patch included, and the `requirements_test.txt` pin line must equal
  the installed version; `holidays`/`cronsim`/`sqlparse` equal HA's manifest pins (the package does not install them).
  Never install `pytest-homeassistant-custom-component` next to it (overlapping fixtures; the guard fails). The package
  brings no `pytest-timeout`/`pytest-cov`; `requirements_test.txt` pins `pytest-timeout` and `pytest-repeat` itself.
  pytest needs `addopts = -p no:respx` (tests/ha/pytest.ini), else it aborts at start with "httpx was already imported".
- `ha-python.txt` must equal the minor HA requires (not the 3.15 of the YAML tooling; Dependabot must not bump it).
- The first `mosquitto` on PATH must be the version the pinned HA Mosquitto app ships (FAILS, never skips; the
  message names the fix). Bump: Dependabot raises the `FROM` line, you add the `# mosquitto-in-app:` mapping line.
  Install: `.github/scripts/install-mosquitto.sh` (copies the binary out of the app image).
- Bump the package and the Dockerfile together, in one PR (Dependabot: multi-ecosystem group `home-assistant`, see the
  comment in `.github/dependabot.yml`).
