# Packages — Feature-specific Claude notes

Directory-scoped knowledge for individual feature packages. Keep the root `CLAUDE.md` general; put
package-specific hardware quirks and design rules here.

## airflow_cooling.yaml — ComfoConnect ventilation

### Boost/preset hardware model
Hardware behaviour of the ComfoConnect unit, relied on by the airflow automations:
- A running **boost** is identified by `switch.comfoconnect_pro_boost` (and the stable `drying_needed`
  intent) — **never** by `preset==high`. Boost only *reports* `high` as a side effect.
- Boost delivers HIGH airflow and **coexists with `auto_mode` ON**. On boost end the preset returns to
  its pre-boost value.
- **Two actions CANCEL a running boost:** (1) writing ANY preset (`low`/`medium`) via
  `select.select_option`, and (2) turning `auto_mode` **OFF** (airflow lingers high a few minutes, then
  reverts). Turning `auto_mode` **ON** does NOT cancel boost.
- `number.comfoconnect_pro_boost_time` is a live countdown; **writing it does NOT extend a running
  boost** in place (the device ignores it) — the value only reaches ~60 again via a switch off→on
  restart.

### Template sensor pattern — trigger-based vs state-based
A derived template `binary_sensor` whose inputs are **only other (slow) binary sensors** MUST be
**state-based** (plain `state:`, no `trigger:`). Trigger-based template sensors restore their last
state on HA **restart** and recompute only when an input **changes** — so a derived-from-binaries
sensor can restore **stale** and never resync (this is what stranded `ventilation_low_needed` at
`off` while `heat_low` was `on` all day, leaving the preset at medium under `heat_protection`).
Reserve trigger-based + restore for **primary** decision sensors driven by continuously-drifting
numeric filters (outdoor temp/dew, weather-station temp): there the drift guarantees a recompute
within ~1 debounce after restart, and restoring preserves the 10-min delay + `this.state` Schmitt
hysteresis. Note the `to: "unknown"` self-trigger covers *reload* (comes up `unknown`), **not**
*restart* (comes up with a restored value), so it does not protect against restart-stale.

### Ventilation controller (`automation.airflow_ventilation_controller`, Section 2) rules
- Gate preset/auto ownership on the **stable intent sensors** (`drying_needed` ⊇ `flush_needed`), NOT
  the boost/auto switches, which flap during boost expiry/re-enable races.
- While a boost is intended/running: write **no preset** and only ever turn `auto_mode` **ON** (or do
  nothing). The boost-owner branch is first in the `choose` and matches on the intent, so the `choose`
  EXITS there and the Low/Medium branches (which turn auto off / write a preset) can never cancel the
  boost. Boost gives HIGH meanwhile, so the underlying preset is moot until boost ends.
- Force `preset=medium, auto=off` only when `drying off`, `flush on`, and the schedule is holding
  `preset=low`; `auto=on, preset=medium` is the preferred state and must not be re-forced.
- Prefer minimal, surgical controller edits over restructures; retain existing branch behaviour unless
  a change is required to fix a specific defect.

## energy.yaml — Energy Dashboard metering

### Dashboard-facing entities are function-named wrappers, never vendor entities
Anything the Energy Dashboard references must be a **function-named** entity that this repo owns —
`sensor.wallbox_power`, `sensor.wallbox_energy` — defined as a thin `template:` wrapper over whatever
integration currently supplies the reading. Never point the dashboard at a vendor/integration entity
(`sensor.evcc_loadpoint_1_*`, `sensor.go_echarger_*`, …) directly.

Rationale: the Energy Dashboard config lives in `.storage/energy` (gitignored, UI-only) and stores
*entity ids*. Long-term statistics are keyed by entity id too. So a vendor entity id in the dashboard
means every source swap costs a manual entity rename to keep history, plus a dashboard edit. With the
wrapper, a swap is a one-line change to `state:`/`availability:` and nothing downstream moves.

Corollaries:
- **Normalise units in the wrapper** from the source's own `unit_of_measurement`
  (`state_attr(src, 'unit_of_measurement')`), rather than hard-assuming the source's scale. Vendor
  firmware picks its own units and a replacement source will differ.
- **Declare `device_class` / `state_class` on the wrapper.** Some discovery payloads omit
  `state_class` (go-e's `total_energy_charged` does), which alone makes an entity unselectable in the
  Energy Dashboard. The wrapper is where that is fixed.
- **Lifetime counters use `state_class: total_increasing`**, so HA absorbs a counter reset and
  baselines on the first observed value instead of booking the pre-existing total as consumption.
- **Never merge two sources into one statistic id.** Two chargers' lifetime counters have different
  absolute baselines; if the new one reads higher, `total_increasing` books the difference as real
  consumption — a phantom spike of potentially thousands of kWh. Start a new series instead.
- Wrappers propagate `unavailable` rather than substituting `0`. A gap in the dashboard is honest;
  a fabricated 0 on a counter is not. (`packages/pergola.yaml`'s PV wrapper maps stale→0 only because
  a downstream rule requires `pv == 0` at night.)
- New source entities need a seed in `tests/conftest.py::baseline_states` — `test_templates.py`
  renders every `state:` template strictly and fails on a sentinel output.
