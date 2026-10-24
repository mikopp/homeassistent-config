# airflow_cooling.yaml — ComfoConnect ventilation

Notes for `packages/airflow_cooling.yaml`. Load only when working on this package.

## Boost/preset hardware model
Hardware behaviour of the ComfoConnect unit, relied on by the airflow automations:
- A running **boost** is identified by `switch.comfoconnect_pro_boost` (and the stable `drying_needed`
  intent) — **never** by `preset==high`. Boost only *reports* `high` as a side effect.
- Boost delivers HIGH airflow and **coexists with `auto_mode` ON**. On boost end the preset returns to
  its pre-boost value.
- **Two actions CANCEL a running boost:** (1) writing ANY preset (`low`/`medium`) via
  `select.select_option`, and (2) turning `auto_mode` **OFF** (airflow lingers high a few minutes, then
  reverts). Turning `auto_mode` **ON** does NOT cancel boost.
- `number.comfoconnect_pro_boost_time` is a live countdown (Modbus holding register 4, seconds on
  the wire, minutes in HA); **writing it does NOT extend a running boost** (the device ignores it).
- **Re-sending boost ON (Modbus coil 6 = 1) while a boost runs RESTARTS the timer at the full
  duration** — verified on the device. This is the seamless re-arm: `switch.turn_on` on the
  already-on boost, no off→on, no notification.
- **A boost-off never restarts the boost.** The drying automation has no `boost_expired` path; only
  `drying_needed` off→on (re)starts it (also adopting a running manual boost), and the countdown
  re-arms it while it runs and drying is still needed. A manual off therefore sticks until the next
  drying cycle.

## Template sensor pattern — trigger-based vs state-based
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

## Ventilation controller (`automation.airflow_ventilation_controller`, Section 2) rules
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

