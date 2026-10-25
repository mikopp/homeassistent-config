# HRDS dehumidifier — design

Package: `packages/hrds_dehumidifier.yaml` (with coordination changes in
`packages/airflow_cooling.yaml`, `packages/heating_pv_boost.yaml` and `packages/energy.yaml`).

> **Status: designed, not implemented.** This page describes the agreed design. The work steps,
> migration and test list are in [`plans/hrds-dehumidifier.md`](../../plans/hrds-dehumidifier.md).
> Once the package exists, this page describes how it behaves.

## What it does

The HRDS+ 30 dehumidifier sits in the supply duct of the Zehnder ComfoAir Q350. Home Assistant
asks it to dehumidify when the house is too humid, **only inside the boost time window**, and
holds the ventilation in the state that makes that run effective: **Q350 at medium, bypass set to
keep outdoor moisture out**. Outside a run the ventilation package works exactly as before.

## The unit facts the design rests on

From the HRDS integration's unit documentation
([`UNIT_BEHAVIOUR.md`](https://github.com/mikopp/homeassistant-innova-hrds/blob/main/doc/references/UNIT_BEHAVIOUR.md),
evidence tags T11–T29):

| Fact | Consequence for the design |
|------|----------------------------|
| Every dehumidify run opens the recirculation damper and runs the HRDS fan; there is no run without recirculation (§9.3) | A run always adds room air through the coil |
| The fan runs at the band minimum, 50 % ≈ **150 m³/h**; Home Assistant cannot set its speed (§9.1, T23–T28) | No fan control in this package. The only airflow lever is the Q350 |
| The HRDS+ 30 is built for **300 m³/h** total through the coil | The Q350 supplies the other 150 m³/h: preset **medium** |
| The compressor starts 6.5–8 min after the request; a stop takes 1–2 min (T11, T18, T19) | Short runs dry nothing: a minimum runtime |
| The dried air is reheated to about room temperature (§2.2) | Dehumidify dries, it does not cool |
| On a brine circuit, active winter dehumidification is forbidden (coil freezing) (§2.2) | No runs in the heating season |

## When the HRDS runs

All of these must hold:

| Condition | Why |
|-----------|-----|
| Automatic control enabled (`input_boolean.hrds_automatic_enabled`) | Master switch |
| Inside the **boost time window** (`binary_sensor.climate_boost_schedule_active`, the same window as the ventilation boost) | Runs are noisy and should happen when the house allows it; one definition of the window for both |
| Not heating season (`sensor.heating_cooling_indicator` ≠ `active_heating`) | Brine circuit, see above |
| The heat pump is **not making hot water** | See [Hot water](#hot-water-pauses-a-run) |

And one of these:

| Reason | Condition |
|--------|-----------|
| **Too humid** | Indoor dew point above the dew point of the *max* humidity. Runs regardless of PV |
| **Humid and the sun pays for it** | Indoor dew point above the dew point of the *target* humidity **and** free PV available, **unless** a ventilation drying boost is pending (outdoor air dry enough to flush for free; the boost goes first) |

Free cooling does not stop a run: free PV makes the extra drying cheap, and free cooling only dries
as far as the outdoor dew allows.

Humidity is compared as **dew point** (absolute moisture), using the same thresholds as the
ventilation package (`sensor.climate_dew_point_target`, `sensor.climate_dew_point_max`), so both
packages agree on what "too humid" means.

**Anti flip-flop.** Each humidity reason has its own Schmitt band: it starts at the threshold and
stops only once the indoor dew point is `input_number.hrds_off_dew_diff` below it. A started run
lasts at least `input_number.hrds_min_runtime`, also when the window closes during it. Only a hot
water charge ends a run early.

Outside the window the HRDS does not run, even above max humidity; the ventilation package's own
moisture logic (flush, low) is the only moisture control then.

## What the ventilation does during a run

While the HRDS dehumidifies (`binary_sensor.hrds_dehumidify_active`: our request is on, or the unit
recirculates for any reason), the ventilation controller suspends its normal logic:

- **Preset medium, auto off.** Together with the 150 m³/h recirculation that gives the 300 m³/h
  the coil is built for. This replaces whatever the ventilation would otherwise do: low (humid or
  hot outdoor air), the auto schedule, a boost.
- **Bypass chosen to keep moisture out.** The Q350 has an enthalpy exchanger, which moves moisture
  from the wetter air stream to the drier one:

  | Intake air vs indoor (dew point) | Profile | Effect |
  |---|---|---|
  | Intake **drier** | `cool` — bypass may open | Dry outdoor air comes in as it is; the exchanger would otherwise hand indoor moisture back to the supply |
  | Intake **wetter** | `warm` — bypass closed | The exchanger moves moisture out of the incoming air into the exhaust |

  The intake dew point is the Q350's own intake sensor, after the ground duct: the air that actually
  enters. During a run this rule alone decides the profile; temperature does not.
- **No boost.** A running boost is cancelled when the run starts; a pending one starts when the run
  ends.
- **Away keeps priority.** In Away mode the preset is left to Away; the bypass rule still applies.

When the run ends, the ventilation controller re-derives its normal state from its own sensors.
Nothing has to be restored.

## Hot water pauses a run

When the heat pump charges the hot-water tank, the HRDS is switched off at once, also inside its
minimum runtime, and the ventilation returns to normal. When the charge ends and the run is still
needed, the HRDS starts again.

The signal is the heating package's hot-water detection without the 25-minute tail that
`binary_sensor.heating_dhw_active` adds for its own return-temperature reading
(`binary_sensor.heating_dhw_running`). If ebusd gives no answer, a running heat pump compressor
(Shelly clamp) counts as possibly hot water; with the compressor off there can be no charge.

## PV and battery

- **Free PV** for the HRDS: the house's PV surplus (`sensor.victron_pv_net_power`) plus the HRDS's
  own draw while its compressor runs (`input_number.hrds_power_demand`), at least that draw. The
  add-back keeps a run from switching itself off by its own consumption. The unit has no power
  reading, so its draw is a setting (handbook maximum 820 W; the steady draw is lower).
- **One battery floor for every PV-surplus load.** The battery gets first call on surplus. The floor
  is one setting in `packages/energy.yaml` (`input_number.energy_pv_min_battery_soc`) with one
  shared sensor (`binary_sensor.energy_pv_battery_ok`), read by the heating PV boost and the HRDS
  alike. Each load keeps its own surplus figure and threshold.

## Who controls what

| Package | Writes | Reads from the other |
|---------|--------|----------------------|
| `hrds_dehumidifier.yaml` | The HRDS dehumidify request (and switches the unit on if it is off) | Drying boost intent, season, hot water |
| `airflow_cooling.yaml` | Every Q350 output: profile, preset, auto mode, boost | `binary_sensor.hrds_dehumidify_active` |

No device is written by both. The ventilation controller stays the only writer of the Q350; the
HRDS package never writes it.

## Safety

- The HRDS integration checks every request (operation gate, Modbus enables, brine temperature
  guard, season). A refused request shows as `blocked` in `sensor.hrds_state`; the package does not
  retry in a loop.
- The package writes only when the wanted state differs from the unit's read-back; never
  periodically.
- The unit is never switched off by the package: in standby it keeps its hourly valve/pump
  anti-stagnation pulses. Switching it off for the winter is a manual, seasonal step.
- Missing data fails safe: an unavailable HRDS reads as "not running", so the ventilation works
  normally.

## Settings

| Setting | Meaning |
|---------|---------|
| `input_boolean.hrds_automatic_enabled` | Automatic control on/off |
| `input_number.hrds_off_dew_diff` | How far (°C dew point) below a threshold the indoor air must fall before a run stops |
| `input_number.hrds_min_runtime` | Shortest run (minutes); must clearly exceed the 6.5–8 min until the compressor starts |
| `input_number.hrds_power_demand` | The HRDS's electrical draw while running (W), for the PV check |
| `input_number.energy_pv_min_battery_soc` | Battery floor for all PV-surplus loads (shared) |
| Boost window schedules (`schedule.climate_boost_*`) | When runs, and ventilation boosts, are allowed |
| Humidity target and max (`input_number.climate_*_humidity`) | The thresholds, shared with the ventilation |

`sensor.hrds_state` says what the package is doing: `off`, `outside_window`, `idle`,
`dehumidify_max`, `dehumidify_pv`, `min_runtime`, `paused_hot_water`, `blocked`.
`sensor.airflow_cooling_state` shows `hrds_dehumidify` during a run.

## Accepted trade-offs

- **Hot days:** during a run the Q350 is at medium even when the ventilation would hold low to keep
  heat out and spare the ground duct. Limited to the window and the run.
- **Humid nights:** above max humidity outside the window, nothing dehumidifies.
- **Bypass is a request, not a command:** `cool` lets the Q350 open the bypass; the Q350 opens it
  only when that also cools. With dry but warm intake air the bypass stays closed and some indoor
  moisture is recovered.
- **Hot water cycles a run:** each charge stops and later restarts the HRDS.
- **Shared PV:** the HRDS and the heating PV boost can see the same surplus at the same moment.
- **One indoor sensor, two controllers:** both packages react to the same indoor dew point. Their
  hysteresis bands, delays and the minimum runtime keep them stable.

## Not part of this design

HRDS cooling (the integration request), changing the HRDS fan band (installer setting),
dehumidifying outside the boost window or in winter.

## Related

- Plan and work steps: [`plans/hrds-dehumidifier.md`](../../plans/hrds-dehumidifier.md)
- Ventilation package notes: [`packages/notes/airflow_cooling.md`](../../packages/notes/airflow_cooling.md)
- HRDS integration: [`mikopp/homeassistant-innova-hrds`](https://github.com/mikopp/homeassistant-innova-hrds)
