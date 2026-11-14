# Heating — HA comfort-temperature helper; `mc/TempDesiredLow` gets no logic

## Overview

Package: `packages/heating_pv_boost.yaml` (Vaillant geoTHERM VWS 82/3 via ebusd). HA pin checked:
`.github/ha-versions/ha/Dockerfile` `FROM ghcr.io/home-assistant/home-assistant:2026.11.1`.

Today `sensor.heating_target_temp` (Phase 2 wanted `mc/TempDesired`) derives from
`sensor.geotherm_heating_temp_desired_low` (`mc/TempDesiredLow`, TDL): out of season TDL, in season
TDL + 1, boost (`active_heating` + slab wanted) TDL + 1 + `input_number.heating_boost_offset`.
The note calls TDL "the only human knob"; `automation.heating_comfort_control` refuses to write
while TDL is unknown.

Why change (owner, 2026-11-14):
- Frost protection is active on the geoTHERM. VWS 82/3 manual (Betriebsanleitung geoTHERM plus
  0020087973_02, §"Regelfrostschutz Heizung", §3.4.2 "Aus"): in ALL operating modes, below 3 °C
  outdoor each heating circuit gets the set Absenktemperatur (= TDL) as target; "Aus" switches the
  circuit off only while frost protection is inactive. So Phase 2's `off` (Loxone warm enough)
  still heats towards TDL below 3 °C outdoors. Observed: outdoor 0 °C, mode `off`, hcmode `heat`,
  `ehp/Hc1Pump` on, compressor off at that moment. **The compressor does start during frost
  protection** (mode `off`, outdoor < 3 °C): owner-verified in the real world, 2026-11-14
  (confirmed fact, not a hypothesis).
- TDL was 21 (= comfort, so `off` was ineffective); the owner has set it to 20 by hand.
- TDL becomes a pure hand-set frost / "off" floor at the panel. Owner: "TempDesiredLow should have
  no logic anymore."
- Raumaufschaltung (room influence) is **off** (owner-confirmed).

Goal: a new HA helper `input_number.heating_comfort_temp` is the only comfort knob;
`sensor.heating_target_temp` derives from it with the same structure; HA neither derives from,
gates on, nor writes TDL.

## Hypotheses (UNVERIFIED)

- **H1 (settle in step 9):** in frost protection the controller ignores the room temperature
  (Raumaufschaltung is off, so there is no room input anyway); the flow setpoint is the heating
  curve at room setpoint TDL, so a house at ~22 °C still gets compressor heat towards a TDL-20
  curve.
- ~~H2~~ settled: the compressor starts during frost protection (owner, 2026-11-14; see Overview).
- **H3 (HA source, unverified at 2026.11.1):** an `input_number` without `initial:` restores its
  last state; a freshly created one starts at `min`. This decides the deploy order (step 8).
  Verify against `homeassistant/components/input_number/__init__.py` at tag `2026.11.1`
  (GitHub API access to `home-assistant/core` was not enabled in the planning session).

## Design

- **New helper** (helpers block, next to `heating_boost_offset`), no `initial:` (rule
  `.claude/rules/ha-yaml.md`):
  ```yaml
  input_number:
    heating_comfort_temp:
      name: "Heating Comfort Temp"
      min: 18        # open question Q1
      max: 24        # open question Q1
      step: 0.5      # open question Q1
      unit_of_measurement: "°C"
      icon: mdi:home-thermometer
      mode: box
  ```
  Comment per K-5: what (the only comfort knob; base of every setpoint HA writes), one-line why
  (TDL is the machine's frost floor, so HA cannot derive comfort from it), pointer to the note.
- **`sensor.heating_target_temp`**: same three branches, `comfort` instead of `tdl`:
  out of season `comfort`, in season `comfort + 1`, boost `comfort + 1 + offset`; `round(1)`.
  Availability: today it is `has_value(TDL)`. Helpers are always available (rule: no float
  defaults, no guard needed for helpers), and the other inputs already render through
  `is_state(...)`, so the `availability:` line is **dropped** and the state reads
  `states('input_number.heating_comfort_temp') | float` without a default. (Q2 asks whether the
  `+ 1` stays, i.e. whether the helper means "TempDesired − 1" or the target itself.)
- **`automation.heating_comfort_control`**: drop `has_value('sensor.geotherm_heating_temp_desired_low')`
  from the template condition; keep `has_value('sensor.heating_target_temp')` (defensive: the
  template entity can still be `unknown` during start-up). Update the comment above it.
- **TDL sensor stays read-only** for display/observation (recommendation; Q3): the MQTT sensor,
  its `?7` poll registration and its `group` entry stay; its comment changes from "The only human
  knob" to "frost / off floor set by hand at the panel; HA reads it for display only, no logic".
  If the owner wants it gone instead: remove sensor, poll line, group entry, test rows in
  `test_heating_pv_boost_ebusd_registers.py` / `test_energy_expire_after.py` / poll test count
  (20 → 19) and the Mosquitto bridge lines become optional.
- Phase 1 notification `heating_slab_charge_decision_changed`: replace "(setback TDL °C)" with
  "(comfort `heating_comfort_temp` °C)".

## Every reader of `sensor.geotherm_heating_temp_desired_low` / `mc/TempDesiredLow`

| Place | What happens |
|---|---|
| `packages/heating_pv_boost.yaml:83-96` MQTT sensor + comment | stays (Q3), comment rewritten |
| `:811-832` `sensor.heating_target_temp` availability + state | reads the helper instead; availability dropped |
| `:1224` poll registration `ebusd/mc/TempDesiredLow/get` | stays (display) |
| `:1398-1401` comfort-control condition | TDL part removed |
| `:1480` Phase 1 notification text | shows comfort helper instead |
| `:1495` group entry | stays; helper added to the "Helpers" group list |
| `dashboards/heating-dashboard.yaml:40` Temperatures card | stays, renamed "Frost / off floor (TempDesiredLow, panel)" |
| `dashboards/heating-dashboard.yaml:218` ebusd Telemetry card | stays |
| `tests/baseline.py:202` seed | stays (sensor still exists); add helper to `BASELINE_NUMBERS` |
| `tests/ha/test_heating_pv_boost.py:693-724` `_TARGET_TABLE` | input `setback` → helper; cases rewritten (step 5) |
| `tests/ha/test_heating_pv_boost_comfort.py` (`_inputs` tdl, `Case.tdl`, `tdl_unknown_writes_nothing`, hold test "TDL moves") | step 5 |
| `tests/ha/test_heating_pv_boost_ebusd_registers.py:46,177-183,338` | unchanged (sensor parse + poll) |
| `tests/ha/test_energy_expire_after.py:63,78` | unchanged |
| `doc/heating_pv_boost/notes.md:46,86,148,164,178,198,348` | step 6 |
| `doc/heating_pv_boost/registers.md:42` (`mc/Params` fallback) | unchanged (register fact) |
| `README.md:55` "derived from `mc/TempDesiredLow`, the only human knob" | rewritten (step 7) |
| `plans/ebusd-pv-heating-optimization.md:37,64-71,80,86` control law `TDL` | cross-ref (step 7) |
| `plans/heating-compressor-cycling.md:78,243,250,339` night-setback test via TDL | cross-ref (step 7) |
| `plans/heating-baseline-and-phase2-prerequisites.md:47,179,197` | no change: "HA never writes TDL" stays true; 179/197 are historical ticks |
| `doc/heating_pv_boost/background.md` | not read (guarded), not changed |

## Steps

### Phase A — code (needs approval)

1. [TODO] **Helper.** Add `input_number.heating_comfort_temp` (Design) with a K-5 comment; add it to
   the `group.heating_pv_boost` Helpers list. Depends on Q1.
2. [TODO] **Target sensor.** Rewrite `sensor.heating_target_temp` on the helper; drop its
   `availability:`; rewrite its comment block ("collapses onto TempDesiredLow" → onto the comfort
   value) per K-5. Depends on Q2.
3. [TODO] **Writer.** Remove the TDL gate from `automation.heating_comfort_control`; update the
   condition comment and the automation `description:` if it names TDL.
4. [TODO] **TDL sensor + notification.** Rewrite the TDL sensor comment (frost/off floor, display
   only, no logic); change the Phase 1 notification text. Optional, comment-only: the
   `heating_boost_offset` comment says the cap is "enforced through its own VR 90 room influence";
   with Raumaufschaltung off that is wrong: reword (check with
   `.github/scripts/yaml_semantic_equal.py`, YAML `#` comment only). Depends on Q3.

### Phase B — tests (read the `ha-test-harness` skill first)

5. [TODO] Tests:
   - `tests/baseline.py`: add `"input_number.heating_comfort_temp": 21` to `BASELINE_NUMBERS`
     (keeps today's 22.0 in-season target, so most expectations stay).
   - `tests/ha/test_heating_pv_boost.py` `_TARGET_TABLE`: the input `setback` (MQTT TDL) becomes the
     helper (set via `input_number.set_value`; check the `Table` harness supports a helper input,
     else set it in the case seeds/actions). Cases: in season comfort + 1 = 22.0; out of season
     21.0; "tracks a changed comfort" 20.0 → 21.0; NEW: a changed TDL (e.g. 17.0) does NOT move
     the target; NEW: boost case comfort + 1 + 1.5 = 23.5 in `active_heating` with slab on (only if
     not already covered by the comfort table row 3; it is, so optional). Reset value must give a
     target no case expects.
   - `tests/ha/test_heating_pv_boost_comfort.py`: add the helper to `_HELPERS` (21); keep TDL
     published (it is a read-back) but at a value ≠ comfort (e.g. 20.0) so a stray TDL derivation
     fails the table; replace `tdl_unknown_writes_nothing` with `tdl_unknown_still_writes` (TDL
     `unknown` → writes as normal); the hold test's "a new TDL moves the setpoint" becomes "a new
     comfort value moves the setpoint" (`input_number.set_value` 22 → `(_TEMP_SET, "23.0")`);
     update the module docstring (read-backs list) and the "TDL 21" comment.
   - Run `.github/scripts/ci-local.sh --package heating_pv_boost` while developing, the full
     `.github/scripts/ci-local.sh` at the end (mandatory), `git ls-files --eol` (no crlf).

### Phase C — docs

6. [TODO] `doc/heating_pv_boost/notes.md` (current facts; one home per fact):
   - Invariant "`mc/TempDesiredLow` is the only human knob" → "`input_number.heating_comfort_temp`
     is the only comfort knob; every setpoint HA writes derives from it; `mc/TempDesired` set at
     the wall is overwritten. `mc/TempDesiredLow` has no HA logic: it is the frost / off floor set
     by hand at the panel."
   - New hardware fact (Hardware quirks, own short subsection "Frost protection"): below 3 °C
     outdoor the circuit heats to TDL in every mode, `off` included (manual 0020087973_02 §
     "Regelfrostschutz Heizung", §3.4.2; owner-confirmed active), and the compressor does start
     then (owner-verified, 2026-11-14). So Phase 2's `off` is a floor at TDL, not "no heat", below
     3 °C. Record via `record-learning` (owner-supplied fact). Whether the room temperature is
     ignored (H1) stays out of the note until step 9 confirms it.
   - Owner-side configuration: `TempDesiredLow` 21 → 20 (owner, 2026-11-14) as the frost floor;
     comfort helper value once set (step 8).
   - Room influence: Raumaufschaltung **off** (owner-confirmed): remove the "Owner action (open)"
     bullet and the Known-biases line; keep the unproven-mechanism bullet if still relevant.
   - Entity map: TDL row "frost/off floor, display only"; add the helper row; target row
     "(comfort, comfort + 1, comfort + 1 + offset; boost only in `active_heating`)".
   - Decisions in force / Writer mechanics: drop "`TempDesiredLow` unknown" from the no-write list.
   - Tests section: "TDL unknown" → "TDL unknown still writes"; mention TDL ≠ comfort in the table.
   - Size stays ≤ 24 KB.
7. [TODO] Dashboard, README and cross-references:
   - `dashboards/heating-dashboard.yaml`: add `input_number.heating_comfort_temp` to the Settings
     card (first row) and to the Temperatures card above the target; rename the target row to
     "Target Temp (derived from comfort, written by Phase 2)"; name the TDL row "Frost / off floor
     (TempDesiredLow, set at panel)".
   - Optional (agreed earlier): relabel "Heat pump is doing (HVAC action)" (line 10) to e.g.
     "Circuit mode (ehp/Status hcmode)": it is the generator's circuit mode, which stays `heat`
     while the pump idles between runs, not real-time activity; optionally also the notes entity-map
     wording "(what the generator does now)".
   - `README.md:55`: setpoint derived from the HA comfort helper; TDL is the machine's frost floor.
     The README "Mode law" bullet (`auto` normally …) is stale since the 2026-11-14 law: noted
     conflict, fix only if the owner wants (Q7).
   - `plans/ebusd-pv-heating-optimization.md`: control-law table and the paragraphs at lines 37, 71,
     80, 86: `TDL` → `comfort` (`input_number.heating_comfort_temp`); add one line: below 3 °C
     outdoor `off` still heats to TDL (frost protection), link this plan.
   - `plans/heating-compressor-cycling.md`: tuning row #0 / step 10 (night setback via TDL): mark
     obsolete, TDL is now the frost floor (pointer to this plan).

### Phase D — owner, after deploy

8. [TODO] Deploy steps (owner; doc from `git diff origin/master...HEAD`):
   1. Before `git pull`, if `input_boolean.heating_comfort_control_enabled` is on: turn it **off**
      (a fresh helper starts at `min`, H3, and the writer would publish `min + 1` at once).
   2. `git pull`, reload/restart HA.
   3. Set `input_number.heating_comfort_temp` once in the UI (Q4; 21 keeps today's target 22.0).
   4. Check `sensor.heating_target_temp` shows the expected value, then re-arm the master switch.
   5. TDL floor at the panel: owner's choice (now 20; Q5).
   No Mosquitto change (no new register, TDL stays read via the existing bridge lines).
9. [TODO] Verification of H1 (owner + agent, read-only via ha-mcp / history): one night with
   outdoor < 3 °C, house ~22 °C, TDL 20, Loxone warm enough (mode `off`). Compare
   `sensor.geotherm_heating_circuit_flow_temp_desired` with the heating curve (0.15) at room
   setpoint TDL 20 vs at the actual room temperature; also watch
   `sensor.geotherm_heating_energy_integral` (`ehp/Integral`),
   `binary_sensor.geotherm_heating_compressor_running` (`ehp/Comp`),
   `sensor.geotherm_heating_circuit_flow_temp` and `binary_sensor.geotherm_heating_circuit_pump`
   (`ehp/Hc1Pump`). Optional cross-check: change TDL by 1 K and see whether the flow setpoint moves
   while the room stays ~22 °C. Record only a confirmed result via `record-learning`; a lower TDL
   (Q5) can follow from it.

10. [TODO] Close: distil into note (step 6 facts, H1 outcome if confirmed), story → background,
    update pointers (slab plan, cycling plan), check the note ≤ 24 KB, delete this plan
    (`doc/KNOWLEDGE.md#K-6`).

## Knowledge homes updated (`doc/KNOWLEDGE.md#K-1`)

- `doc/heating_pv_boost/notes.md` (invariant, frost-protection fact, owner config, room influence,
  entity map, writer, tests).
- YAML comments in `packages/heating_pv_boost.yaml` (K-5).
- `README.md` package section; `plans/ebusd-pv-heating-optimization.md` and
  `plans/heating-compressor-cycling.md` cross-references.
- No design doc, skill or rule change expected.

## Open questions for the owner

- **Q1** Helper range/step: suggested min 18, max 24, step 0.5. OK?
- **Q2** Keep the `+ 1` (helper = "base", in-season target = helper + 1, as with TDL today) or make
  the helper the in-season target itself (target = helper, boost = helper + offset)? The plan
  carries over `+ 1` as asked; dropping it is simpler to read on the dashboard.
- **Q3** Keep the TDL sensor as read-only display (recommended) or remove it entirely?
- **Q4** Comfort value to set after deploy: 21 (target stays 22.0)?
- **Q5** TDL floor: stay at 20, or lower (17–18) so frost protection (which runs the compressor)
  heats less while Loxone says warm enough? Depends partly on step 9.
- **Q6** Is frost-protection heating with compressor runs towards TDL while Loxone says warm enough
  acceptable (it cannot be switched off from HA; only TDL limits it)?
- **Q7** Fix the stale README "Mode law" bullet (`auto` normally) in the same PR?
- **Q8** Relabel the "Heat pump is doing (HVAC action)" row (optional step 7) in this PR?

## Status

Awaiting approval. Plan written 2026-11-14; no implementation started. Next: owner answers
Q1–Q8 and approves Phase A.

- [TODO] 1–4 Phase A (code)
- [TODO] 5 Phase B (tests)
- [TODO] 6–7 Phase C (docs, dashboard, cross-refs)
- [TODO] 8–9 Phase D (owner deploy, verification)
- [TODO] 10 Close
