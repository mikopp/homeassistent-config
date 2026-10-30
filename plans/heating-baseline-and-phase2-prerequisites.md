# Heating — baseline data retention and Phase 2 prerequisites

Pinned HA: `ghcr.io/home-assistant/home-assistant:2026.10.1` (`FROM` line of
`.github/ha-versions/ha/Dockerfile`, read 2026-10-30).

## Context

A review of the two heating plans found gaps that neither covers. They are prerequisites, not new
features. This plan only covers those gaps and does not change the intent of:

- `plans/ebusd-pv-heating-optimization.md` (the "slab plan"): steps 8, 8c, 10, 11 (Phase 2), 12.
- `plans/heating-compressor-cycling.md` (the "cycling plan"): steps 6, 7 (baseline, `CompHysteresis`
  +1 K, cold-weather step-back).

It is independent of the airflow and Victron plans. Nothing here edits those two plans' text except
(optionally, with approval) ticking boxes / adding cross-references in their Status sections.

No code is changed by writing this plan. Every step below needs explicit approval before it starts.

## Verified findings

Each was re-checked against the code at base `0a4cab0` (master, includes #129-#134).

| # | Finding | Evidence |
|---|---|---|
| A | Raw history is purged after 5 days. The cycling plan's step 7 needs a 3-day baseline, then a `CompHysteresis` change, then a comparison "a week later" (about 10 days after the baseline starts), plus a cold-weather step-back. The baseline days will be gone by the comparison. | `configuration.yaml` l.7-8: `recorder: purge_keep_days: 5` (comment l.4-6 says LTS is separate and kept) |
| A2 | Entities without `state_class` get no long-term statistics (LTS), so after 5 days nothing is left: `sensor.geotherm_heating_compressor_start_integral` (l.~214-224), `..._compressor_hysteresis` (l.~237), `..._backup_start_integral` (l.~249) have a unit but no `state_class`. The history_stats sensors, `binary_sensor.heating_compressor_active`, `sensor.geotherm_heating_hvac_mode` and `..._hvac_action` have none either. The settings are the ones that matter most: they are what makes two baselines comparable. | `packages/heating_pv_boost.yaml` l.214-255, l.155-161; history_stats l.525-552 |
| B | The Phase 2 write path is not documented. The Mosquitto bridge is an explicit allowlist. Phase 2 must publish to `ebusd/mc/OperatingMode/set` and `ebusd/mc/TempDesired/set`. The notes only describe `in` lines and `/get out` lines; "`/set`" appears in neither the slab plan nor the notes (grep of `plans/`, `packages/notes/`, `packages/CLAUDE.md` finds no ebusd `/set`). | `packages/notes/heating_pv_boost.md` "Transport" (l.26-41); slab plan l.150-160 |
| C | `sensor.geotherm_heating_compressor_starts` (unique_id `heating_compressor_starts`) has `state_class: total_increasing` but no `unit_of_measurement`. Sibling counters have units (`h`, `kWh`). The daily `utility_meter` built on it inherits this. Owner reports a utility_meter warning and unitless LTS. | `packages/heating_pv_boost.yaml` l.258-266; utility_meter l.556-560 |
| D | The daily meters and history_stats only exist since the 2026-10-30 ~16:06 deploy. The first complete baseline day is 2026-10-31. Today's partial day must not be counted. | deploy time reported by owner |
| E | `sensor.geotherm_heating_hvac_mode` is an MQTT sensor with no availability handling, so an HA or MQTT restart produces `unavailable`/`unknown`. Counting "mode flips" as raw state changes would count restarts. Only changes between real values (`auto`, `on`, `low`, `off`) count. The two time-program switches per day (`on` by day, `low` at night) are expected and are not cycling (cycling plan step 0b). | `packages/heating_pv_boost.yaml` l.158-161; cycling plan l.66-67 |
| F | Owner/UI state that blocks later steps (checklist below). | see "Owner checklist" |
| G | The new counters (`CompStartsHc`, `CompHoursHc`, `YieldTotal`) and the three derived meters have never been seen incrementing live: the compressor has not run since the deploy of the cycling work. All 9 registers answered `ebusctl read` (cycling plan 6b), but HA-side increments are unverified. | cycling plan Status 6 still unchecked |

## Decisions (settled by the owner, 2026-10-30)

1. **Retention (finding A): A1, `purge_keep_days` 5 -> 14.** Check the DB size first (step 1). Revert
   once the tuning work is finished (Status 7). The `state_class` idea for the settings sensors (A3)
   is not done: a setting is not a measurement; record each change (date, old, new) in the cycling
   plan's Observations instead.
2. **Unit name (finding C): `count`** (owner's choice; matches the unit of a plain counter).
3. **Statistics repair (finding C): accepted as planned.** After the unit change use "Fix issue" to
   update the stored unit (little history is at stake, data began 2026-10-30). The exact repair text
   at 2026.10.1 is still unverified; confirm it on the live instance before telling the owner what to
   click.
4. **Bridge write lines (finding B): only `OperatingMode/set` and `TempDesired/set`.** Not
   `TempDesiredLow` (HA never writes it). **ebusd accepts writes: verified by the owner**, so no
   separate access-level investigation is needed (see step 2).
5. **Cross-reference edits to the slab and cycling plans: approved** (step 6 below). `step 10` is
   ticked from live data; `step 8c` is NOT ticked (the helper is still 30 and is the owner's UI
   change). `Hc1Pump` is not needed by any step in these plans (Phase 2 uses the Shelly-based
   `binary_sensor.heating_compressor_active`, which the owner chose), so it is not added.
   `input_boolean.heating_pv_boost_enabled` is the owner's switch; this work never changes it.

## Step 1 — Recorder retention (finding A) — approval required

Design (A1, decided):

1. User-side, read-only first: check the current recorder DB size (`home-assistant_v2.db` on the HA
   host, or `sensor.database_size` if installed; ha-mcp `ha_get_system_health` may show it). Record
   the number in this plan.
2. `configuration.yaml`: change `purge_keep_days: 5` to `14` and update the comment above it
   (it currently says "purged after 5 days"). Keep the statement that LTS is separate.
3. Do not add `purge_keep_days` per entity (not supported). Do not add `commit_interval` changes.
4. After deploy (user, via `git pull` + HA restart; recorder config needs a restart): confirm the
   states table keeps data beyond 5 days after 5+ days pass; confirm the DB growth is in line with the
   estimate.
5. When the tuning work (cycling plan steps 7, 7a) is finished, decide whether to revert to 5 d.
   Record this as a follow-up in Status, do not leave it forgotten.

Tests: none (global config, no template). Verified by yamllint and `check_config` (see Verification).

## Step 2 — Phase 2 write path: Mosquitto bridge lines (finding B) — approval required

Docs only plus a manual user step. No HA YAML change.

Design:

1. `packages/notes/heating_pv_boost.md`, "Transport: the bridge is an allowlist": add one paragraph.
   The bridge is `in` for state topics and `out` for `/get`. **Writes need a third kind of line:**
   `topic ebusd/<circuit>/<name>/set out 0`. Phase 2 therefore needs two more lines. State the rule
   (every register HA writes needs a `/set out` line) and not the topic list.
2. Slab plan: in the Phase 2 description (step 11) add a "Prerequisite (manual, user)" bullet that
   links to this plan's exact lines. Also add the lines to the slab plan's Transport section after the
   "As deployed" note. (Edits to the slab plan text need explicit approval; see Risks.)
3. The exact lines to add, modeled on the documented allowlist style. **Manual user-side step, on the
   HA broker host, in the same file as the existing `ebusd-bridge` connection block** (the block's
   `connection` name and address stay as deployed; do not create a second connection):

   ```
   topic ebusd/mc/OperatingMode/set out 0
   topic ebusd/mc/TempDesired/set out 0
   ```

   then **restart** Mosquitto (a reload does not load bridge changes, as for the compressor lines).
   The existing documented `in` lines for `ebusd/mc/OperatingMode` and `ebusd/mc/TempDesired` and the
   `/get out` lines (poll registration, l.976-980) already exist and stay.
4. Post-deploy check (user, no code): `mosquitto_pub` of the value that is already current to
   `ebusd/mc/TempDesired/set` on HA's broker host (idempotent write of the current value, for example
   the present `TempDesired`), then watch that ebusd logs the write and `sensor.geotherm_heating_temp_desired`
   (state topic `ebusd/mc/TempDesired`, l.139) keeps/updates. Do not test with a different value.
5. ebusd write access for these two registers is **already verified by the owner**; the idempotent
   write in point 4 only proves the new bridge lines.

No HA-side automation is added here. Phase 2 (slab step 11) will publish; this step only removes the
blocker.

## Step 3 — Unit on the compressor starts counter (finding C) — approval required

Design:

1. `packages/heating_pv_boost.yaml` (sensor `heating_compressor_starts`, l.258-266): add
   `unit_of_measurement: "count"` next to `state_class`. Keep the `value_template` unchanged
   (`| int`). Add a one-line comment saying why (utility_meter and LTS need a unit).
2. Effect on dependants:
   - `utility_meter.heating_compressor_starts_daily` (l.556-560) takes its unit from the source, so it
     will read `count` after a restart. No YAML change.
   - `sensor.geotherm_heating_compressor_starts` and the daily meter have `state_class`, so LTS exist.
     Their stored statistics unit was none; the recorder will report a mismatch (see decision 3).
     Do not rename `unique_id` or the entity id (that would break the dashboard card at l.1157/l.1166
     and orphan the history).
   - Dashboard (`dashboards/heating-dashboard.yaml`) and tests only reference entity ids and states,
     not units; expected unaffected. Check with grep before editing.
3. Confirm the recorder behavior and the exact repair text at 2026.10.1 before telling the user what
   to click; if it cannot be confirmed without a live instance, say so in the PR (unverified).
4. Tests: `tests/conftest.py` l.353 seeds the entity as
   `ha.set_state("sensor.geotherm_heating_compressor_starts", "20000", {"state_class": "total_increasing"})`.
   Add `"unit_of_measurement": "count"` to keep the seed realistic. No new test is needed for a unit
   on an MQTT sensor; the harness does not run a real broker.

## Step 4 — Baseline method (findings D, E) — approval required (docs only)

Write the exact counting rules into `packages/notes/heating_pv_boost.md` (new short section
"Baseline method") and link it from cycling plan step 7 (on approval):

- **First full baseline day is 2026-10-31.** 2026-10-30 is partial (meters began ~16:06) and is
  excluded. A baseline = 3 consecutive full days with comparable weather (record the daily mean
  outdoor temperature next to each day).
- **Starts per day:** use `sensor.heating_compressor_starts_daily` (machine counter, heating only).
  `sensor.heating_compressor_runs_today` counts every Shelly run including hot water; use it only as a
  cross-check, expect it to be higher.
- **Mode flips:** count only transitions of `sensor.geotherm_heating_hvac_mode` between two values in
  {`auto`, `on`, `low`, `off`}. Ignore any transition into or out of `unavailable`/`unknown` (HA or
  MQTT restart). Expected normal: 2 per day (the time program). A restart-free day with more than 2
  is the signal, not the raw count.
- **Settings:** log `CompHysteresis`, `CompIntegral` and `BackupIntegral` at the start of every
  baseline day, and every change with date and time.
- **Retention:** every number is read within the retention window, or copied into Observations
  (decision 1).
- **Compressor vs circulation:** `binary_sensor.heating_compressor_active` is the Shelly clamp
  (> 500 W). `ehp/Hc1Pump` is not read (slab plan Observations finding 4); a run of the circulation
  pump alone should stay below 500 W, but that is an inference, not a measurement.

Tests: none (docs).

## Step 5 — Post-deploy verification of the counters (finding G) — user-side, no code

After the deploy has run through at least one compressor start, the user (or Claude read-only via
ha-mcp) checks:

- `sensor.geotherm_heating_compressor_starts`, `..._compressor_hours`, `..._yield_total` increase
  (state_class `total_increasing`, no reset to 0 shown as a negative delta).
- `sensor.heating_compressor_starts_daily` and `sensor.heating_yield_daily` increase by the same
  amount as the raw counters since midnight.
- `sensor.heating_electricity_daily` is non-zero, which also proves that
  `sensor.technikraum_heizung_heizung_energy` is the real Shelly entity id (cycling plan step 6).
- `sensor.heating_compressor_last_run_minutes` and `sensor.heating_compressor_stop_temp` update after
  the first full run; `sensor.heating_compressor_runs_today` matches the observed number of runs.
- The three settings sensors are not `unavailable`.

Results go into the cycling plan's Observations, not into `.claude/learnings.md` (not proven
mechanisms, just checks).

## Step 6 — Cross-reference edits to the existing plans (docs only) — approved, run last

- Slab plan (`plans/ebusd-pv-heating-optimization.md`):
  - step 10: tick, note "live TDL 21 / TempDesired 22, 2026-10-30".
  - step 11 (Phase 2): add a prerequisite line pointing to this plan's step 2 (two `/set out` bridge
    lines, ebusd writes already verified by the owner).
  - Transport "As deployed" note: add the `/set out` line kind.
  - 8c: leave unticked (live value is still 30; owner's UI change).
- Cycling plan (`plans/heating-compressor-cycling.md`): step 7 gets a note that retention is 14 d
  (this plan, step 1) and a link to the baseline method (step 4); first full baseline day 2026-10-31.
- Do not change any other text in those plans.

## Owner checklist (finding F) — UI / hardware, no code

These are not implemented by Claude. Tick them in the Status section when done.

- [ ] `input_number.heating_pv_min_battery_soc` is **30**; slab plan step 8c wants **50** (the Victron
      floor is 30, so the gate never blocks at 30). Set in the HA UI. Helpers must not get `initial:`
      (repo rule), so this is a one-time UI change.
- [ ] `input_boolean.heating_pv_boost_enabled` is **off**. This is the owner's switch: Claude never
      changes it. Slab plan step 12 (boost) cannot produce decision data until the owner arms it.
- [x] Slab plan step 10 (real `mc/TempDesiredLow`): live TDL 21, TempDesired 22; ticked in the slab
      plan by step 6 (docs edit).
- [x] `ehp/Hc1Pump`: not needed by any step in either plan, so it is not added (owner decision rule:
      only if needed). The Shelly > 500 W inference stays. Re-open only if a later step needs it.

## Tests and the harness

- Test harness: `tests/` with `conftest.py` (`baseline_states` seeds), `test_heating_pv_boost.py`
  (the heating tests; helpers `_drive_season`, `_seed_power_flows`). It runs HA in the pinned image.
- Steps 1 and 2 add no testable logic. Step 3 only touches a seed attribute in `tests/conftest.py`
  l.353. Run the full `tests/` suite in CI to confirm nothing keyed on the unitless seed breaks.
- Do not add tests for the bridge lines or retention; they are host/deploy configuration.

## Risks

- **Retention costs disk.** 14 d is about 2.8x the raw state history. Check size first; the recorder
  config needs a restart; purging happens at 04:12 nightly so growth appears gradually.
- **Unit change creates a statistics repair** for two entities (decision 3) and can make the Energy/
  statistics panel show a warning until it is resolved. Little history is at stake (data began
  2026-10-30).
- **Writing to the heat pump.** Step 2 only opens the path and tests with the already-current value.
  The first real write is Phase 2 (slab step 11), which has its own approval. A wrong `/set out` line
  or access level fails silently (the write never arrives), so the post-deploy check matters.
- **Docs edits to the existing plans.** Editing the slab and cycling plans changes documents others
  work from. Do it only with approval, in the Status/cross-reference spots, and not in parallel with
  other work on those files.
- **Bridge restarts.** Restarting Mosquitto briefly disconnects all MQTT clients (Victron, Shelly,
  ebusd); do it at a quiet time.
- All of step 2 and 5 cannot be tested in the CI harness; nothing here has been seen live.

## Verification

- yamllint on `configuration.yaml` and `packages/heating_pv_boost.yaml`;
  `.github/scripts/fix_yaml_style.py .`; `resolve_ha_yaml.py configuration.yaml .`.
- `check_config` against the pinned image (Dockerfile `FROM`).
- CI pytest (full suite).
- `git ls-files --eol` shows no `w/crlf` or `i/crlf`.
- After deploy (user): step 1 point 4, step 2 point 4, step 3 point 3, step 5 checklist.

## Status

- [x] 0. Plan file (this file)
- [ ] 1. Measure DB size (user, pre-deploy); [x] `purge_keep_days` 5 -> 14 done in code
- [ ] 2. [x] Notes paragraph + slab plan docs done; USER still to add the two lines and
      restarts Mosquitto; idempotent write test
- [ ] 3. [x] `unit_of_measurement: "count"` + conftest seed done; USER still to
      handle the statistics repair (update stored unit)
- [x] 4. Write the "Baseline method" section in `packages/notes/heating_pv_boost.md`; link from
      cycling plan step 7
- [ ] 5. Post-deploy counter verification (after the first compressor run)
- [x] 6. Cross-reference edits (done 2026-10-30, docs only): slab plan (Phase 2 bridge prerequisite, tick step 10) and cycling plan
      (step 7 retention + baseline method link); 8c stays open (owner)
- [ ] 7. Follow-up: revert retention to 5 once the tuning is finished
- [ ] Owner: SOC to 50 (slab 8c); `heating_pv_boost_enabled` is the owner's switch
