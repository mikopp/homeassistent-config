# HRDS dehumidifier — design

Package: `packages/hrds_dehumidifier.yaml`, dashboard `dashboards/hrds-dashboard.yaml`, with
coordination changes in `packages/airflow_cooling.yaml`, `packages/heating_pv_boost.yaml` and
`packages/energy.yaml`.

> **Status: designed, not implemented.** This page describes the agreed design. The work steps,
> deploy and test list are in [`plans/hrds-dehumidifier.md`](../../plans/hrds-dehumidifier.md).
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

Always required:

| Condition | Why |
|-----------|-----|
| The HRDS is **switched on** (`sensor.unit_status` on) | Switching the unit on or off is the owner's choice; the automation never does it. Unit off means the automation is off |
| The automation is enabled (`input_boolean.hrds_automatic_enabled`) | Its own enable switch, like every automation in this repo |
| Not heating season (`sensor.heating_cooling_indicator` ≠ `active_heating`) | Brine circuit, see above |
| The heat pump is **not making hot water** | See [Hot water](#hot-water-pauses-a-run) |

**At home** — only inside the **boost time window** (`binary_sensor.airflow_boost_window_active`,
the same window as the ventilation boost; runs are noisy), for one of these reasons:

| Reason | Condition |
|--------|-----------|
| **Too humid** | Indoor dew point above the dew point of the *max* humidity. Runs regardless of PV |
| **Humid and the sun pays for it** | Indoor dew point above the dew point of the *target* humidity **and** free PV available, **unless** a ventilation drying boost is pending (outdoor air dry enough to flush for free; the boost goes first) |

**In Away** (`binary_sensor.airflow_away_active`: the Q350's away function on, or Away lifted for
a run, see below) — nobody is home, so the **boost window is ignored**. The HRDS runs when the indoor dew point is above the *target* dew point and one of:

| Reason | Condition |
|--------|-----------|
| **The sun pays for it** | Free PV available |
| **Double down on a flush** | The ventilation package wants to flush moisture (`binary_sensor.airflow_humidity_flush_needed`: outdoor air drier than indoor). The ventilation flushes dry air at medium and the HRDS dries the recirculated air at the same time |

Free cooling does not stop a run: free PV makes the extra drying cheap, and free cooling only dries
as far as the outdoor dew allows.

Humidity is compared as **dew point** (absolute moisture), using the ventilation package's own
thresholds and indoor reading (`sensor.airflow_dew_point_target`, `sensor.airflow_dew_point_max`,
`sensor.airflow_min_indoor_dew_5min`, set through `input_number.airflow_target_humidity` and
`_max_humidity`). Both packages therefore agree on what "too humid" means; the HRDS package depends
on the ventilation package for it.

**Anti flip-flop.** Each humidity reason has its own Schmitt band: it starts at the threshold and
stops only once the indoor dew point is `input_number.hrds_off_dew_diff` below it. A started run
lasts at least `input_number.hrds_min_runtime`, also when the window closes during it. Only a hot
water charge ends a run early.

**Nights.** At home, outside the window the HRDS does not run, even above max humidity. That is
deliberate: the ventilation package's own moisture logic (flush, low) handles moisture then.

## What the ventilation does during a run

While the HRDS dehumidifies (`binary_sensor.hrds_dehumidify_active`: our request is on, or the unit
recirculates for any reason — also a dehumidify you start by hand), the ventilation controller
suspends its normal logic:

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
  enters (`binary_sensor.airflow_intake_drier`). During a run this rule alone decides the profile;
  temperature does not.
- **No boost.** A running boost is cancelled when the run starts; a pending one starts when the run
  ends.
- **Medium also in Away.** The Away level is far too little air for the coil. When a run starts in
  Away, the ventilation controller lifts Away for the run (turns the Q350's away function off and
  marks it in `input_boolean.airflow_away_lifted`), holds medium like at home, and switches Away
  back on when the run ends. While Away is lifted the house still counts as Away for every rule
  (`binary_sensor.airflow_away_active`): no boost, no boost window. Coming home during a run:
  switch off "Away (lifted for dehumidify)" on the dehumidifier dashboard, then Away is not
  restored. (If the Q350 turns out to accept preset medium while Away stays on, the design writes
  only the preset instead.)

When the run ends, the ventilation controller re-derives its normal state from its own sensors.
Nothing has to be restored.

## Hot water pauses a run

When the heat pump charges the hot-water tank, the HRDS is switched off at once, also inside its
minimum runtime, and the ventilation returns to normal. When the charge ends and the run is still
wanted, the HRDS starts again. For notifications it is still the same run.

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
- **No priority between loads yet.** The heating PV boost and the HRDS can see the same surplus at
  the same moment. Which one goes first is a later plan ([`plans/todo.md`](../../plans/todo.md)).

## Notifications

One message when a run starts (why: too humid, free PV, or in Away free PV or a flush) and one
when it ends (why: humidity reached, window closed, automatic control turned off, the unit switched
off, or the unit refused the request; and how long it ran). Nothing else: a hot-water pause and its restart are silent, and the ventilation
package does not report its hold or the hand-back afterwards. The ventilation's own messages resume
three minutes after a run.

## Dashboard

`dashboards/hrds-dashboard.yaml` ("Dehumidifier" in the sidebar) shows on one page:

- the unit (climate card) and what it does: dehumidify request, compressor, fan, recirculation,
  water valve and temperatures, season;
- whether it can run: operation gate, brine guard, setup and water checks, alarms;
- the automation: `sensor.hrds_state`, the reasons, the boost window, the hot-water pause, the
  minimum-runtime timer;
- the ventilation during a run: state, Q350 volume, preset, profile, intake-drier, bypass estimate;
- moisture history (indoor dew against the target and max dew points, intake dew), the solar
  figures, the settings, and a logbook of runs.

## Who controls what

| Package | Writes | Reads from the other |
|---------|--------|----------------------|
| `hrds_dehumidifier.yaml` | The HRDS dehumidify request only | Boost window, Away, drying boost and flush intent, humidity thresholds, season, hot water, battery floor |
| `airflow_cooling.yaml` | Every Q350 output: profile, preset, auto mode, boost | `binary_sensor.hrds_dehumidify_active` |

No device is written by both. The ventilation controller stays the only writer of the Q350; the
HRDS package never writes it.

## Safety

- The HRDS integration checks every request (operation gate, Modbus enables, brine temperature
  guard, season). A refused request shows as `blocked` in `sensor.hrds_state` and ends the run; the
  package does not retry in a loop.
- The package writes only when the wanted state differs from the unit's read-back; never
  periodically.
- The package never switches the unit on or off. Switched on, it idles in standby (keeping its
  hourly valve/pump anti-stagnation pulses) until a run; switched off, the automation does nothing.
  If the unit is switched off during a run, the package clears its own dehumidify request, so the
  unit does not start on a stale request when it is switched on again.
- Missing data fails safe: an unavailable HRDS reads as "not running", so the ventilation works
  normally.

## Settings

| Setting | Meaning |
|---------|---------|
| `switch.unit_on_off` (integration) | The HRDS itself on/off — yours, never touched by the automation |
| `input_boolean.hrds_automatic_enabled` | The automation on/off |
| `input_boolean.airflow_away_lifted` | Shown as "Away (lifted for dehumidify)": on while a run has lifted Away. Switch it off to end Away during a run |
| `input_number.hrds_off_dew_diff` | How far (°C dew point) below a threshold the indoor air must fall before a run stops |
| `input_number.hrds_min_runtime` | Shortest run (minutes); must clearly exceed the 6.5–8 min until the compressor starts |
| `input_number.hrds_power_demand` | The HRDS's electrical draw while running (W), for the PV check |
| `input_number.energy_pv_min_battery_soc` | Battery floor for all PV-surplus loads (shared) |
| `schedule.airflow_boost_workday` / `_non_workday` | When runs, and ventilation boosts, are allowed |
| `input_number.airflow_target_humidity` / `_max_humidity` | The thresholds, shared with the ventilation |

`sensor.hrds_state` says what the package is doing: `off` (automation disabled), `unit_off`,
`outside_window`, `idle`, `dehumidify_max`, `dehumidify_pv`, `dehumidify_away_pv`,
`dehumidify_away_flush`, `min_runtime`, `paused_hot_water`, `blocked`.
`sensor.airflow_cooling_state` shows `hrds_dehumidify` during a run.

## Accepted trade-offs

- **Hot days:** during a run the Q350 is at medium even when the ventilation would hold low to keep
  heat out and spare the ground duct. Limited to the window and the run.
- **Humid nights:** at home, above max humidity outside the window, the HRDS does not run.
- **Away with humid outdoor air:** in Away the HRDS runs only on free PV or alongside a flush, so
  with humid outdoor air and no sun it does not run.
- **Away is lifted during a run:** the Q350 leaves its Away level for the run (more air, more
  noise in an empty house), and the away switch itself reads off meanwhile; the dashboard shows
  the lift. A hot-water pause restores Away until the run resumes.
- **Bypass is a request, not a command:** `cool` lets the Q350 open the bypass; the Q350 opens it
  only when that also cools. With dry but warm intake air the bypass stays closed and some indoor
  moisture is recovered.
- **Hot water cycles a run:** each charge stops and later restarts the HRDS.
- **Shared PV:** see above; no priority yet.
- **One indoor sensor, two controllers:** both packages react to the same indoor dew point. Their
  hysteresis bands, delays and the minimum runtime keep them stable.

## Not part of this design

HRDS cooling (the integration request), changing the HRDS fan band (installer setting),
dehumidifying outside the boost window at home or in winter, PV priority between loads, and moving the
shared humidity settings out of the ventilation package (both in
[`plans/todo.md`](../../plans/todo.md)).

## Related

- Plan and work steps: [`plans/hrds-dehumidifier.md`](../../plans/hrds-dehumidifier.md)
- Ventilation package notes: [`packages/notes/airflow_cooling.md`](../../packages/notes/airflow_cooling.md)
- HRDS integration: [`mikopp/homeassistant-innova-hrds`](https://github.com/mikopp/homeassistant-innova-hrds)
