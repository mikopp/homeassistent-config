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
