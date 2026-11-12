---
paths:
  - "packages/energy.yaml"
  - "tests/ha/test_energy_wallbox.py"
  - "tests/ha/test_energy_pool_pump.py"
  - "plans/energy-live-entity-ids.md"
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
  firmware picks its own units and a replacement source will differ (go-e API v2 is natively W / Wh,
  but its discovery payload may declare kW / kWh).
- **Declare `device_class` / `state_class` on the wrapper.** Some discovery payloads omit
  `state_class` (go-e's `total_energy_charged` does), which alone makes an entity unselectable in the
  Energy Dashboard. The wrapper is where that is fixed.
- **Lifetime counters use `state_class: total_increasing`**, so HA absorbs a counter reset (e.g. a charger factory reset) and
  baselines on the first observed value instead of booking the pre-existing total as consumption.
- **Never merge two sources into one statistic id.** Two chargers' lifetime counters have different
  absolute baselines; if the new one reads higher, `total_increasing` books the difference as real
  consumption — a phantom spike of potentially thousands of kWh. Start a new series instead.
- Wrappers propagate `unavailable` rather than substituting `0`. A gap in the dashboard is honest;
  a fabricated 0 on a counter is not. (`packages/pergola.yaml`'s PV wrapper maps stale→0 only because
  a downstream rule requires `pv == 0` at night.)

### Loxone appliance sensors: no `expire_after`
Loxone publishes only on change, has no heartbeat (an idle appliance is silent for hours or days),
publishes a 0 when a draw ends and retains its last value for new subscribers. So the Loxone sensors
have **no `expire_after`**: it would turn them unavailable while idle and break the Energy
Dashboard; the held last value is the true draw (running) or 0 (idle). Loxone sometimes publishes
an empty payload; their `value_template` passes it through as `''` (kept last value, no warning) — rule and source evidence in
the `ha-mqtt` skill.

## Hardware / integration quirks

| Device | Integration / topics | Payload and units |
|---|---|---|
| Pool Pump, Rain Water Pump (Shelly Plus Plug S: `shellyplusplugs-pool-pump`, `shellyplusplugs-rainwaterpump`) | MQTT `shelly/<device>/status/switch:0` (JSON) | `apower` W; `aenergy.total` lifetime **Wh** → ÷1000 kWh; `voltage`, `current`, `output` (switch) |
| Heizung (Shelly Pro 3EM `shellypro3em-heizung`) | bridged from a separate mosquitto broker under the `shelly/` prefix; `em:0`, `emdata:0` | Gen2/3 EM schema differs from Plug S: `em:0.total_act_power` already W; `emdata:0.total_act` cumulative all-phase **Wh** → ÷1000 kWh |
| Washer, Tumble Dryer, Dishwasher (Loxone) | MQTT `loxone/<device>/power`, `loxone/<device>/energy`; `<device>` ∈ `washer`, `tumble-dry` (hyphen in the topic, underscores in HA ids), `dishwasher` | plain numeric (not JSON), 3 decimals; power natively **kW** (no scaling); energy lifetime kWh, updated at least every 5 min while it changes, silent when idle |
| Wallbox (go-e Charger, serial `291401`) | the charger firmware's own MQTT auto-discovery: `homeassistant/<domain>/go-e_291401/*`, data `go-eCharger/<key>` | power from `nrg` (`nrg[11]`, all phases); energy from `eto` (lifetime, natively Wh); `total_energy_charged` ships without `state_class` |

- Shelly lifetime counters reset only on a factory reset; `total_increasing` absorbs a reboot dip.
- All Shelly entities use `expire_after: 120`; the Loxone ones have none (invariant above).
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
- Wallbox power is display-only and goes unavailable when the charger drops off MQTT, rather than
  reporting a misleading 0.

## Known biases / open issues
- MQTT sensors without `default_entity_id`: ids depend on the old registry (#146).

## Tests
- `tests/ha/test_energy_wallbox.py`: one looping test over the go-e SOURCE entities (explicit units, energy
  without `state_class`), asserting on the WRAPPER, so the template incl. unit normalisation (W/kW,
  Wh/kWh) and availability run. Source entities have no real path in CI and are seeded.
- `tests/ha/test_energy_pool_pump.py`: Shelly Plus Plug S payloads go over the real broker through
  the real `value_template`s; every case checks all five entities (power, energy, voltage,
  current, switch).
- New source entities need a seed in `tests/baseline.py`; `tests/ha/test_templates.py` renders every
  `state:` template strictly and fails on a sentinel output.
- `tests/ha/test_energy_loxone.py`: the six Loxone washer/tumble-dry/dishwasher power and energy
  sensors (and `loxone/heating/warm_enough`) get the live broker payloads over the real broker, plus
  non-zero power sequences (representative kW values, not captured), rounding, whitespace and empty
  payloads (ignored, last value kept), and their units are asserted. A non-numeric payload on these
  six is not tested: their template guards only the empty payload (it would raise).

## Related
- `doc/heating_pv_boost/notes.md` — consumer of the Heizung Pro 3EM power/energy.
- `ha-energy-metering`, `ha-mqtt` skills.
