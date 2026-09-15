# ebusd PV Heating Optimisation — slab pre-charging from PV surplus

## Context

The house has a Vaillant geoTHERM brine-to-water heat pump on ebus, a Victron PV + battery system,
and a Loxone Miniserver that today decides when the house needs heat and writes the geoTHERM's
heating mode directly.

Goal: use midday PV surplus to over-charge the underfloor slab so the house coasts through evening
and night without drawing grid or house battery.

The slab is the only thermal store in the system — `uih/EhpHeatBufferAvailable` reads `off` and both
buffer sensors read `cutoff` (no tank fitted). That is why `ehp/HcReturnTemp` reads directly on slab
charge state, and why a "thermal battery" strategy is viable at all.

### Division of responsibility

Each system does only what it uniquely knows:

| System | Owns |
|---|---|
| Loxone | Human comfort. Publishes one boolean: *is the house warm enough?* Stops writing the heat pump. |
| Home Assistant | Energy. Computes PV surplus, decides slab mode, writes two registers. |
| Vaillant | The machine. Weather compensation, VR 90 room influence, compressor protection, outdoor cutoff. |

HA writes only `mc/OperatingMode` and `mc/TempDesired`, and only ever `low` or `on` — **never
`off`**. That single rule makes the worst failure state "slightly cool", never "no heat".

### Control law

| Heating season | Slab mode | Loxone says | `mc/OperatingMode` | `mc/TempDesired` |
|---|---|---|---|---|
| off | — | — | `low` | `TDL` |
| on | no | warm enough | `low` | `TDL + 1` |
| on | no | heat needed | `on` | `TDL + 1` |
| on | yes | *ignored* | `on` | `TDL + 1 + offset` |

`TDL` = `mc/TempDesiredLow`, the only human knob. Heating season =
`sensor.heating_cooling_indicator` in (`active_heating`, `neutral`).

### Why the setpoint is derived, not captured

`TempDesired` is computed from `TempDesiredLow` every time, so there is nothing to save and restore
across a boost or an HA restart. Always compute the **absolute** target — never apply a relative
`current + offset`, which is not idempotent and would compound to `+2×offset` on a retry or a
restart mid-boost.

### Why grid export is not the surplus signal

The Victron battery absorbs surplus first, so `sensor.victron_grid_power_export` only goes positive
once the battery is full — too late in the day to charge a slab. And naive "generation minus load"
self-cancels: once the boost draws 2 kW, measured surplus drops by 2 kW and the boost cancels
itself. The surplus sensor therefore excludes the heating circuit's own draw, making it invariant
under our own action.

### Rejected alternatives

- **HA rebuilds room comfort from HA room sensors.** Loxone already holds per-room setpoints and
  weighting. Duplicating it would drift. Comfort during a boost is instead bounded by the offset
  cap, enforced by the Vaillant's own VR 90 room influence — so HA needs no room sensors at all.
- **HA writes `off` to stop heating.** Removing `off` from HA's vocabulary is what makes every
  failure path safe.
- **`--mqttjson`.** The Loxone integration consumes these topics in the plain `;`-separated form
  and would break.

## Changes

### 1. `packages/heating_pv_boost.yaml` — new

Phase 1 (this step) is the **read-only decision layer**: ebusd telemetry, PV surplus, interlocks,
and `binary_sensor.heating_slab_mode_wanted` computing the full decision without acting on it.

### 2. `tests/conftest.py`

Seed every new MQTT-sourced entity in `baseline_states`; `test_templates.py` renders every `state:`
template strictly and fails on a sentinel output.

### 3. `packages/CLAUDE.md`

Verified register findings that outlive this plan (see that file).

## Post-deploy steps on the HA host (manual — user deploys via `git pull`)

1. Confirm `ebusd/ehp/HcReturnTemp` is published. It reads fine on demand but was not in the
   observed topic sample. To enable polling without editing ebusd config, publish `?5` to
   `ebusd/ehp/HcReturnTemp/get`.
2. Confirm `ebusd/mc/TempDesiredLow`, `ebusd/ehp/Backup` and `ebusd/uih/CoolingActive` arrive. If a
   topic never appears, the sensor stays `unavailable` — that is the signal, and the documented
   fallback for `TempDesiredLow` is `mc/Params` field 1.
3. Leave `--mqttjson` **off**.

## Status

- [x] 1. In-repo plan file
- [x] 2. `packages/heating_pv_boost.yaml` — Phase 1 read-only decision layer
- [x] 3. `tests/conftest.py` seeds for the new MQTT entities
- [x] 4. `packages/CLAUDE.md` — register findings
- [x] 5. `README.md` — package section
- [x] 6. `tests/test_heating_pv_boost.py` — surplus, derived setpoint, DHW mask, interlocks
- [ ] 7. Observe for several days; calibrate the return-temp saturation threshold
- [ ] 8. Loxone: publish `warm_enough`; stop writing the geoTHERM heating mode
- [ ] 9. Vaillant: set a real `mc/TempDesiredLow` below the intended day temperature
- [ ] 10. Phase 2 — comfort control (`low`/`on` + derived setpoint)
- [ ] 11. Phase 3 — slab boost
- [ ] 12. Phase 4 — tests, dashboard

### Checks run locally

- `yamllint -c .yamllint.yaml packages/heating_pv_boost.yaml` — clean, no warnings
- `.github/scripts/fix_yaml_style.py .` — "All files already clean", no diff
- `.github/scripts/resolve_ha_yaml.py configuration.yaml .` → `yamllint` — clean (3241 lines)
- `.github/scripts/extract_templates.py` — 12 strict `state:` templates, 17 runtime, all extracted
- **`homeassistant --script check_config` against the pinned image (2026.9.1) — PASSES**, with
  `secrets.yaml` from `fakesecrets.yaml`, the injected Linz coordinates, the `climate_template`
  custom component and the workday fixture, exactly as CI does it
- `--script check_config --info all` confirms all 18 new entities are loaded, so the package is
  genuinely parsed rather than silently skipped
- `python3 -m ast` parse of `tests/conftest.py` and `tests/test_heating_pv_boost.py`

### Not runnable in this environment

- `pytest tests/` (needs a live HA container via `ha_integration_test_harness`), so
  `tests/test_heating_pv_boost.py` is written against the documented harness API and the existing
  test patterns but has not been executed — CI is its first run
- Anything touching the real MQTT broker or the ebus, so every topic name and payload shape is
  taken from the captured dump rather than observed live
