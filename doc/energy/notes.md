---
paths:
  - "packages/energy.yaml"
  - "tests/ha/test_energy_*.py"
  - "plans/energy-*.md"
---
# energy package notes (`packages/energy.yaml`)

Current facts of the energy package: MQTT power/energy sensors of metered devices for the Energy
Dashboard, plus the function-named wallbox wrappers. Loads with `packages/energy.yaml` and its
tests. No design doc (below the K-4 threshold). Generic platform/statistics knowledge (Riemann,
`utility_meter`, entity migration): `ha-energy-metering` skill. MQTT `unique_id`/empty-payload
rules: `ha-mqtt` skill.

## Invariants
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
- **Declare `device_class` / `state_class` on the wrapper.** A source without `state_class` is
  unselectable in the Energy Dashboard, and discovery payloads do not always carry it. The wrapper is
  where that is fixed.
- **Never merge two sources into one statistic id.** Two chargers' lifetime counters have different
  absolute baselines; if the new one reads higher, `total_increasing` books the difference as real
  consumption — a phantom spike of potentially thousands of kWh. Start a new series instead (it
  baselines on its first value).
- Wrappers propagate `unavailable` rather than substituting `0`. A gap in the dashboard is honest;
  a fabricated 0 on a counter is not.

### Loxone appliance sensors: no `expire_after`
Loxone publishes only on change, has no heartbeat (an idle appliance is silent for hours or days),
publishes a 0 when a draw ends and retains its last value for new subscribers. So the Loxone sensors
have **no `expire_after`**: it would turn them unavailable while idle and break the Energy
Dashboard; the held last value is the true draw (running) or 0 (idle). Loxone sometimes publishes
an empty payload; the `value_template` keeps the last value (`ha-mqtt` skill).

## Hardware / integration quirks

| Device | Integration / topics | Payload and units |
|---|---|---|
| Heizung (Shelly Pro 3EM `shellypro3em-heizung`) | bridged from a separate mosquitto broker under the `shelly/` prefix; `em:0`, `emdata:0` | Gen2/3 EM schema differs from the Plug S `switch:0` schema: `em:0.total_act_power` already W; `emdata:0.total_act` cumulative all-phase **Wh** → ÷1000 kWh |
| Washer, Tumble Dryer, Dishwasher (Loxone) | MQTT `loxone/<device>/power`, `loxone/<device>/energy` | plain numbers; publish on change only (invariant above) |
| Wallbox (go-e Charger, serial `291401`) | the charger firmware's own MQTT auto-discovery: `homeassistant/<domain>/go-e_291401/*`, data `go-eCharger/<key>` | power from `nrg` (`nrg[11]`, all phases); energy from `eto` (lifetime, natively Wh) |

- The go-e source entities are owned by the MQTT integration; their ids can change if the device is
  re-paired. In YAML only the wallbox wrapper's `state:`/`availability:` reference them; the seeds
  in `tests/baseline.py` and `tests/ha/test_energy_wallbox.py` must change with them.

## Entity map
MQTT entities here have no `default_entity_id` (#146), so their ids are not derivable (rule in
`.claude/rules/ha-yaml.md`); look them up via ha-mcp `ha_get_entity(unique_id=...)`. Live lookup
is open: `plans/energy-live-entity-ids.md`.

| Entity | unique_id | Notes |
|---|---|---|
| `sensor.wallbox_power` / `sensor.wallbox_energy` | `wallbox_power` / `wallbox_energy` | template wrappers; the Energy Dashboard's wallbox entities |
| `sensor.go_echarger_homekopp_power_total`, `sensor.go_echarger_homekopp_total_energy_charged` | (discovery) | wallbox wrapper sources |
| `sensor.technikraum_heizung_heizung_power` | `shelly_pro3em_heizung_power` | used by `heating_pv_boost` and the heating dashboard |
| `sensor.technikraum_heizung_heizung_energy` (unverified, derived like the power id) | `shelly_pro3em_heizung_energy` | source of `heating_pv_boost`'s `heating_electricity_daily` |
| pool pump: power, energy, voltage, current, `switch` (binary) | `shelly_pool_pump_*` | on a fresh registry (tests) `sensor.pool_pool_pump_pool_pump_*` (#146); live ids not verified |
| rain water pump: same set | `shelly_rainwater_pump_*` | |
| washer / tumble dryer / dishwasher: power (kW), energy (kWh) | `loxone_washer_*`, `loxone_tumble_dry_*`, `loxone_dishwasher_*` | |

## Decisions in force
- The wallbox comes from the go-e firmware's own MQTT discovery, not evcc: the previous evcc
  loadpoint 1 sensors republished far too slowly to track a live charge session.

## Known biases / open issues
- None beyond #146 (Entity map).

## Tests
- The Plug S energy template's `aenergy is not none` guard is not testable: a null block is silent
  with or without it (an undefined attribute logs nothing, `ha-test-harness`). The Pro 3EM's
  `total_act is not none` guard is tested: without it a null `total_act` logs a warning
  (`tests/ha/test_energy_shelly.py`).
- A non-numeric payload on the six Loxone meters is not tested, accepted by the owner: their template
  guards only the empty payload, so it would raise (warning, last value kept).

## Related
- `doc/heating_pv_boost/notes.md` — consumer of the Heizung Pro 3EM power/energy.
- `ha-energy-metering`, `ha-mqtt` skills.
