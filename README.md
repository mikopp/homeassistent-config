# Home Assistant Configuration

My personal [Home Assistant](https://www.home-assistant.io/) configuration for a house in Linz, Austria.

The setup uses a modular **packages** pattern — each feature lives in its own YAML file under `packages/`, keeping concerns separated and testable. A CI pipeline runs on every push to validate the configuration, lint YAML, and execute integration tests against a live HA instance.

---

## Packages

### `packages/pergola.yaml` — Bioclimatic Pergola
Fully automated control of a Somfy-driven bioclimatic pergola roof (two synchronized covers).

- **State machine**: transitions through `frost`, `rain`, `rain_stopped`, `user_override`, and multiple sun-tracking states
- **Sun tracking**: calculates optimal slat angle from solar azimuth/elevation geometry; separate angles for heating vs. cooling season
- **Rain recovery**: timed drain sequence (8° → 15° progressive opening) before resuming normal operation
- **Inputs**: on/off toggle, heating/cooling mode selector, PV conversion factor, geometric parameters (east/west orientation offsets)
- **Template sensors**: effective sun angle, computed slat angle, tilt position, MaxOpenEast/West bounds, lower position limits

### `packages/airflow_cooling.yaml` — Ventilation & Humidity Control
Automation for a ComfoConnect ERV (energy-recovery ventilator) via the [comfoconnect](https://github.com/michaelarnauts/aiocomfoconnect) custom component.

- **Free cooling**: detects when outdoor air is dry and cool enough to bypass heat recovery and flush the house
- **Humidity flushing**: boost mode triggered by high indoor humidity, schedule-gated (workday vs. weekend)
- **Profile selection**: `warm` (moisture retention) → `comfort` → `cool` (bypass fully open), driven by dew-point thresholds
- **Sensors**: derived dew point, filter status, boost countdown

### `packages/heating_cooling_indicator.yaml` — Seasonal Indicator
A simple template sensor that classifies the current season based on a 48-hour mean of outdoor temperature.

- States: `active_heating` → `neutral` → `passive_cooling` → `active_cooling`
- Hysteresis thresholds prevent oscillation at boundaries
- Used by other packages (pergola, airflow) to select appropriate behaviour profiles

### `packages/victron.yaml` — Victron Energy System
MQTT-based monitoring of a Victron solar/battery/grid installation (MPPT charger + AC-coupled PV inverter + MultiPlus 3-phase).

- **Sensors**: battery SOC, voltage and current; per-phase grid power (L1/L2/L3); PV generation; system losses
- **Energy accumulation**: trigger-based kWh integration sensors for solar, grid import/export, and load
- **Utility meters**: monthly billing meters aligned to the Austrian tariff reset date (1st of month)
- **Status**: charger/inverter mode detection, system state

---

## Dashboards

Custom [Lovelace](https://www.home-assistant.io/dashboards/) dashboards in YAML mode, loaded via `configuration.yaml`.

| File | URL | Purpose |
|------|-----|---------|
| `dashboards/Pergola-management.yaml` | `/pergola-management` | Full pergola control panel: cover positions, sun angles, mode selector, state history |
| `dashboards/airflow-dashboard.yaml` | `/airflow-monitoring` | Ventilation monitoring: ERV profile, humidity sensors, dew point, boost controls |

Dashboard element fragments live in `dashboards/elements/` and are included via `!include`.

---

## Blueprints

| Path | Purpose |
|------|---------|
| `blueprints/automation/mine/loxone_inputs.yaml` | Bridges pergola cover and door-lock state to a Loxone Miniserver via REST |
| `blueprints/automation/homeassistant/` | Standard HA-provided blueprints (motion light, zone departure notification) |
| `blueprints/script/homeassistant/` | Standard HA-provided script blueprints (confirmable notification) |

---

## CI / GitHub Actions

### `ha_check.yaml` — HA Config Validation + Integration Tests
Runs on every push. Validates the full configuration and executes the test suite against a live HA Docker instance.

1. Pulls the pinned HA Docker image (cached by `.HA_VERSION`)
2. Installs custom component dependencies listed in `tests/custom_components.yaml` from GitHub
3. Copies `fakesecrets.yaml` → `secrets.yaml` so the config loads without real credentials
4. Runs `homeassistant --script check_config` to catch invalid configuration
5. Extracts all Jinja2 templates from YAML files into `/tmp/templates.json`
6. Runs `pytest tests/` against a session-scoped live HA container — covers template rendering correctness and automation scenario tests
7. Posts a PR comment with truncated pytest output on failure
8. Writes full results to the Actions Job Summary

### `yaml-lint.yml` — YAML Style + Lint
Runs on every push as a separate job chain.

1. **fix-yaml-style**: auto-fixes trailing whitespace, CRLF line endings, and missing trailing newlines; commits the fixes back if any changes are detected
2. **lint-yaml**: runs `yamllint` with the rules in `.yamllint.yaml`
3. **lint-resolved**: resolves all `!include` directives in `configuration.yaml` and dashboards (expanding to a flat file), then lints the resolved output — catches issues that only appear after include expansion

---

## Secrets

Credentials and local IP addresses are stored in `secrets.yaml` (excluded from the repository via `.gitignore`). The file `fakesecrets.yaml` contains placeholder entries used by CI in place of the real secrets file.

Copy `fakesecrets.yaml` to `secrets.yaml` and fill in your actual values before running Home Assistant locally.

---

## Tests

The `tests/` directory contains a `pytest` suite:

| File | Coverage |
|------|----------|
| `test_templates.py` | Renders every state template and runtime template extracted from YAML; asserts no rendering errors |
| `test_pergola.py` | Automation scenarios for the pergola state machine (rain detection, frost lock, sun tracking transitions) |
| `test_airflow.py` | Automation scenarios for ventilation profile switching and humidity boost logic |
| `test_victron.py` | Template sensor correctness for energy accumulation and mode detection |
