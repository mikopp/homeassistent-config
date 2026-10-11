# energy.yaml — Energy Dashboard metering

Notes for `packages/energy.yaml`. Load only when working on this package.

## Dashboard-facing entities are function-named wrappers, never vendor entities
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

