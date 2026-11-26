# heating_pv_boost: design

Current decision tables of `packages/heating_pv_boost.yaml`. Read on demand; the rules an agent
must know before editing are in `doc/heating_pv_boost/notes.md` (auto-loaded). IDs are stable:
never renumber, mark retired IDs as gone.

## HPB-1 Comfort control law (Phase 2)

Implemented by `sensor.heating_wanted_operating_mode` (mode) and `sensor.heating_target_temp`
(setpoint), written by `automation.heating_comfort_control`. First matching row wins (owner):

| # | Indicator | Slab mode wanted | Loxone `warm_enough` | `mc/OperatingMode` | `mc/TempDesired` |
|---|---|---|---|---|---|
| 1 | `unknown` / `unavailable` | — | — | unchanged | unchanged |
| 2 | `passive_cooling` / `active_cooling` | — (never) | — | **`off`** | `C` |
| 3 | `active_heating` | **on** | any (overridden) | **`on`** | `C + 1 + offset` |
| 4 | `active_heating` | off / `unknown` | on | **`off`** | `C + 1` |
| 5 | `active_heating` | off / `unknown` | off / `unknown` / `unavailable` / silent 24 h | **`on`** | `C + 1` |
| 6 | `neutral` | — (never) | on | **`off`** | `C + 1` |
| 7 | `neutral` | — (never) | off / `unknown` / `unavailable` / silent 24 h | **`on`** | `C + 1` |

- `C` = `input_number.heating_comfort_temp`, the only comfort knob while the writer is armed
  (with it off, `number.geotherm_heating_temp_desired` sets `mc/TempDesired` by hand); `offset` =
  `input_number.heating_boost_offset`. `mc/TempDesiredLow` is not an input (the unit's frost
  floor): below 3 °C outdoor, rows 4 and 6 (`off`) still heat towards it. Rests on: (device VWS-6)
- Slab boosting happens only in `active_heating` (owner: in the shoulder season the slab needs
  little heat and an over-charge mostly overheats). `binary_sensor.heating_slab_mode_wanted` is
  `unknown` for 20 min after every restart and counts as off.
  `binary_sensor.heating_season_active` (`active_heating` or `neutral`) gates rows 3–7.
- Row 3 is live as soon as both `input_boolean.heating_pv_boost_enabled` and
  `input_boolean.heating_comfort_control_enabled` are on: the slab boost has no writer of its own.
- Edges: a boost ending while Loxone says warm enough → row 4, `off`; a boost starting while the
  mode is `off` → row 3, `on`.
- Every mode change respects the 30 min hold (longer than the unit's minimum time between
  compressor starts). A `TempDesired`-only change (row 3 ↔ row 5, mode stays `on`) does not start
  or stop the compressor and is not held (UNPROVEN: Known gaps). Rests on: (device VWS-10, VWS-25)
- Rows 4 and 6 still write `C + 1`, and `TempDesired` is computed from `C` every time (absolute,
  never `current + offset`, which would compound on a retry or a restart mid-boost), so nothing
  has to be saved or restored across a mode change, a boost or an HA restart.
- The row order matches `sensor.heating_control_state` (cooling → off-season → slab → … → warm
  enough → heating).
- Row 2 writes `off` in the cooling season: the heating mode is its own register, separate from
  the cooling setting, so `off` is expected not to disturb cooling (untested: Known gaps).
  Rests on: (device VWS-15)
- Spec of `tests/ha/test_heating_pv_boost_comfort.py` (rows 1-7 as a table).

## HPB-2 Energy modes

`sensor.heating_energy_mode` (owner-defined, first match wins):

| Condition | Mode | Counts as |
|---|---|---|
| `ehp/Comp` on, `hvac_action` = `water` | `water_heating` | hot water |
| `ehp/Comp` on | `active_heating` | heating |
| `ehp/Hc1Pump` on, `hvac_action` = `water` | `water_heating` (hot-water run-on) | hot water |
| `ehp/Hc1Pump` on, `hvac_action` = `cooling` | `cooling` | cooling: no yield, no SPF |
| `ehp/Hc1Pump` on | `passive_heating` | heating |
| otherwise | `off` | standby |

- The hot-water run-on row has not fired in the charge ends checked: hcmode leaves `water`
  before the compressor stops, and the tail runs at heating power into the heating circuit, so
  `active_heating` books it, the right bucket. Rests on: (device VWS-13)
- The geoTHERM cools passively only: the compressor never runs for cooling, so checking
  the compressor first is safe. Rests on: (device VWS-14)
- Cooling is `hvac_action` (what the machine does now), not `binary_sensor.heating_cooling_active`
  (which also fires on a mere need or request; the interlock keeps that wider OR). hcmode is
  not the compressor state, hence `ehp/Comp` first. Rests on: (device VWS-1, VWS-32)
- Yield buckets: `active_heating` and `passive_heating` share `space_heating` because
  `ehp/YieldTotal` (the only yield register) steps in whole kWh at the slowest poll, so an active
  cycle's last kWh often arrives after the switch to the passive cycle. `cooling`/`off` yield
  should stay 0; growth there shows misbooking at the other mode boundaries. Rests on: (device
  VWS-29)
- Efficiency = SPF H4 = (environmental yield + electricity) ÷ electricity: `YieldTotal` is the
  heat taken from the ground, not delivered heat, and the Shelly clamp meters the whole unit
  (compressor, brine and heating pumps, controls, standby, hot water), hence boundary H4. Space
  heating = (`space_heating` yield + active + passive electricity) ÷ that electricity; hot water
  likewise with the water bucket; combined over all modes. An estimate (±~10 %): the unit has no
  brine flow meter, and yield + electricity slightly overstates delivered heat (standby and case
  losses never reach the water). Rolling 30 days = from the 30-day sums of long-term
  statistics, never a mean of daily ratios; `unknown` below 10 kWh electricity (a whole-kWh
  yield step then moves it ≤ 2.5 %). Rests on: (device VWS-29)

## Known gaps

- HPB-1 "a `TempDesired`-only change does not start or stop the compressor" is UNPROVEN: the
  integral counts VF2 − W, not the fine setpoint (device VWS-3), but whether such a write can
  start or stop a run by another path is an open device question (device VWS-25). The not-held
  rule rests on it; settling it: `plans/heating-curve-tuning.md` step 0.11.
- HPB-1 row 2: that heating mode `off` leaves cooling running is untested (device VWS-15);
  settling it: `plans/heating-cycling-from-ehp.md` step 14.
