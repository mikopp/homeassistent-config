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

Research findings (2026-11-14; installation manual for exactly this unit: *Návod k instalaci
geoTHERM plus* 0020132514_00, model table VWS 82/3 = 0010009074, Czech edition, quotes translated;
agrees with the Italian geoTHERM plus manual 0020092583_02 and the German /2 screen diagram
"Raumaufschaltung: Keine"). VERIFIED from the manual, to be recorded in step 6:
- Raumaufschaltung = controller menu C5 (shown only with a VR 90 connected), also settable on the
  VR 90; three options, factory "Keine":
  - **Keine**: the VR 90 room temperature "is not taken into account during heating operation".
  - **Aufschaltung**: the curve's flow setpoint is shifted by (room desired − room actual); a warm
    room lowers it. No factor/formula documented.
  - **Thermostat**: heating stops at room desired + 1 K, released below desired. The manual says
    not to use it with energy-balance control (this unit, no buffer tank).
  - Not a cataloged ebusd register (not in the published 08.ehp, 50.ehp.mc, 75.rcc, 15.uih).
- Frost protection (installation manual): below 3 °C outdoor with no time window active (`Aus`, or
  `Eco` outside a window), after a default **1 h delay**, a flow-temperature request with the
  Absenk room setpoint (TDL) is generated; it ends above 4 °C.
- Slab charging: Thermostat would block a boost (the warm room trips it), Aufschaltung would weaken
  it; Keine is the right setting (owner's reason for turning it off holds).
- `doc/heating_pv_boost/background.md` says "off/thermostat": there are three options.

Goal: a new HA helper `input_number.heating_comfort_temp` is the only comfort knob;
`sensor.heating_target_temp` derives from it with the same structure; HA neither derives from,
gates on, writes nor reads TDL: the TDL sensor is removed (Q3).

## Hypotheses (UNVERIFIED)

- **H1 (settle in step 9):** in frost protection the controller ignores the room temperature;
  the flow setpoint is the heating curve at room setpoint TDL, so a house at ~22 °C still gets
  compressor heat towards a TDL-20 curve. Supporting evidence: with C5 = Keine the manual says
  the room temperature is ignored "during heating operation"; no source says explicitly that this
  covers the frost request. Owner accepts frost-protection heating either way (Q6), so H1 is
  informative only and blocks nothing.
- **H4 (unproven lead):** the C5 setting may be an uncataloged `mc` register at `b509 0d2400`
  (that address is `RemoteControlMode` "Raumaufschaltung" in 50.zeo.mc.csv). Read-only check:
  `ebusctl hex 50b509030d2400` before/after switching C5. Not needed for this plan.
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
      min: 18        # Q1: owner OK
      max: 24
      step: 0.5
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
  `states('input_number.heating_comfort_temp') | float` without a default. The `+ 1` stays (Q2).
- **`automation.heating_comfort_control`**: drop `has_value('sensor.geotherm_heating_temp_desired_low')`
  from the template condition; keep `has_value('sensor.heating_target_temp')` (defensive: the
  template entity can still be `unknown` during start-up). Update the comment above it.
- **TDL sensor is removed** (Q3): the MQTT sensor `sensor.geotherm_heating_temp_desired_low`,
  its `?7` poll registration, its `group` entry, its dashboard rows and its test rows go. The
  poll test's expected count drops 20 → 19. After deploy the owner deletes the orphaned entity
  (and its long-term statistics, if HA offers it) and may drop the two Mosquitto bridge lines for
  `ebusd/mc/TempDesiredLow` (optional, harmless if left).
- Phase 1 notification `heating_slab_charge_decision_changed`: replace "(setback TDL °C)" with
  "(comfort `heating_comfort_temp` °C)".

## Every reader of `sensor.geotherm_heating_temp_desired_low` / `mc/TempDesiredLow`

| Place | What happens |
|---|---|
| `packages/heating_pv_boost.yaml:83-96` MQTT sensor + comment | removed (Q3) |
| `:811-832` `sensor.heating_target_temp` availability + state | reads the helper instead; availability dropped |
| `:1224` poll registration `ebusd/mc/TempDesiredLow/get` | removed |
| `:1398-1401` comfort-control condition | TDL part removed |
| `:1480` Phase 1 notification text | shows comfort helper instead |
| `:1495` group entry | removed; helper added to the "Helpers" group list |
| `dashboards/heating-dashboard.yaml:40` Temperatures card | row removed (helper row added) |
| `dashboards/heating-dashboard.yaml:218` ebusd Telemetry card | row removed |
| `tests/baseline.py:202` seed | removed; add helper to `BASELINE_NUMBERS` |
| `tests/ha/test_heating_pv_boost.py:693-724` `_TARGET_TABLE` | input `setback` → helper; cases rewritten (step 5) |
| `tests/ha/test_heating_pv_boost_comfort.py` (`_inputs` tdl, `Case.tdl`, `tdl_unknown_writes_nothing`, hold test "TDL moves") | step 5 |
| `tests/ha/test_heating_pv_boost_ebusd_registers.py:46,177-183,338` | TDL rows removed; poll count 20 → 19 |
| `tests/ha/test_energy_expire_after.py:63,78` | TDL rows removed |
| `doc/heating_pv_boost/notes.md:46,86,148,164,178,198,348` | step 6 |
| `doc/heating_pv_boost/registers.md:42` (`mc/Params` fallback) | unchanged (register fact) |
| `README.md:55` "derived from `mc/TempDesiredLow`, the only human knob" | rewritten (step 7) |
| `plans/ebusd-pv-heating-optimization.md:37,64-71,80,86` control law `TDL` | cross-ref (step 7) |
| `plans/heating-compressor-cycling.md:78,243,250,339` night-setback test via TDL | cross-ref (step 7) |
| `plans/heating-baseline-and-phase2-prerequisites.md:47,179,197` | no change: "HA never writes TDL" stays true; 179/197 are historical ticks |
| `doc/heating_pv_boost/background.md` | not changed (history; its "off/thermostat" is superseded by the step 6 note fact) |

## Steps

### Phase A — code (needs approval)

1. [DONE] **Helper.** Add `input_number.heating_comfort_temp` (Design) with a K-5 comment; add it to
   the `group.heating_pv_boost` Helpers list. Depends on Q1.
2. [DONE] **Target sensor.** Rewrite `sensor.heating_target_temp` on the helper; drop its
   `availability:`; rewrite its comment block ("collapses onto TempDesiredLow" → onto the comfort
   value) per K-5. Depends on Q2.
3. [DONE] **Writer.** Remove the TDL gate from `automation.heating_comfort_control`; update the
   condition comment and the automation `description:` if it names TDL.
4. [DONE] **Remove TDL + notification.** Remove the TDL MQTT sensor, its poll registration line
   and its group entry; change the Phase 1 notification text. Comment fix: the
   `heating_boost_offset` comment says the cap is "enforced through its own VR 90 room influence";
   with Raumaufschaltung = Keine there is no room influence: reword.

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
   - `tests/ha/test_heating_pv_boost_comfort.py`: add the helper to `_HELPERS` (21); stop
     publishing TDL (`_inputs`, `Case.tdl`); delete `tdl_unknown_writes_nothing` (no TDL input any
     more); the hold test's "a new TDL moves the setpoint" becomes "a new comfort value moves the
     setpoint" (`input_number.set_value` 22 → `(_TEMP_SET, "23.0")`); update the module docstring
     (read-backs list) and the "TDL 21" comment.
   - `tests/baseline.py`: remove the TDL seed. `test_heating_pv_boost_ebusd_registers.py`: remove
     the TDL payload rows, poll count 20 → 19. `test_energy_expire_after.py`: remove the TDL rows.
     Grep `tests/` for `temp_desired_low` / `TempDesiredLow` afterwards: no hit may remain.
   - Run `.github/scripts/ci-local.sh --package heating_pv_boost` while developing, the full
     `.github/scripts/ci-local.sh` at the end (mandatory), `git ls-files --eol` (no crlf).

### Phase C — docs

6. [TODO] `doc/heating_pv_boost/notes.md` (current facts; one home per fact):
   - Invariant "`mc/TempDesiredLow` is the only human knob" → "`input_number.heating_comfort_temp`
     is the only comfort knob; every setpoint HA writes derives from it; `mc/TempDesired` set at
     the wall is overwritten. `mc/TempDesiredLow` has no HA logic and is not read: it is the
     frost / off floor set by hand at the panel; its value does not matter to HA (owner)."
   - New hardware fact (Hardware quirks, own short subsection "Frost protection"): below 3 °C
     outdoor with no time window active (`Aus`, `Eco` outside a window), after a default 1 h
     delay, the circuit heats towards TDL; ends above 4 °C (installation manual 0020132514_00;
     user manual 0020087973_02 § "Regelfrostschutz Heizung", §3.4.2; owner-confirmed active). The
     compressor does start then (owner-verified, 2026-11-14). So Phase 2's `off` is a floor at TDL,
     not "no heat", below 3 °C; accepted (owner). Record via `record-learning`. H1 stays out of the
     note unless confirmed.
   - Owner-side configuration: comfort helper value (21, set by hand); TDL is the owner's panel
     setting, no longer listed as a value HA depends on.
   - Room influence: replace the "Raumaufschaltung" bullets with the verified C5 facts (three
     options Keine / Aufschaltung / Thermostat and their effect, Thermostat not for energy-balance
     control, set at controller C5 or VR 90, not a cataloged register; source installation manual
     0020132514_00); state **Keine** is set (owner-confirmed) and why (slab charging). Remove the
     "Owner action (open)" bullet, the unproven "only gates `mc/RoomTempOffset`" bullet (replace by
     H4 as an open lead only if kept in a plan) and the Known-biases line.
   - Entity map: remove the TDL row; add the helper row; target row
     "(comfort, comfort + 1, comfort + 1 + offset; boost only in `active_heating`)".
   - Decisions in force / Writer mechanics: drop "`TempDesiredLow` unknown" from the no-write list.
   - Tests section: drop the "TDL unknown" test mention; the poll test's 20 → 19 `/get`
     priorities.
   - Size stays ≤ 24 KB.
7. [TODO] Dashboard, README and cross-references:
   - `dashboards/heating-dashboard.yaml`: add `input_number.heating_comfort_temp` to the Settings
     card (first row) and to the Temperatures card above the target; rename the target row to
     "Target Temp (derived from comfort, written by Phase 2)"; remove both TDL rows.
   - No relabel of the "Heat pump is doing (HVAC action)" row (Q8: owner, leave it).
   - `README.md:55`: setpoint derived from the HA comfort helper; TDL is the machine's frost floor.
     README "Mode law" bullet: rewrite to the current law (Q7: yes).
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
   3. Set `input_number.heating_comfort_temp` once in the UI to 21 (owner; no `initial:`).
   4. Check `sensor.heating_target_temp` shows 22.0 in season, then re-arm the master switch.
   5. Delete the orphaned `sensor.geotherm_heating_temp_desired_low` (Settings → Entities) and its
      statistics if Developer tools → Statistics lists them.
   6. Optional: drop the Mosquitto bridge lines `topic ebusd/mc/TempDesiredLow in 0` and
      `topic ebusd/mc/TempDesiredLow/get out 0` (restart Mosquitto); harmless if left.
9. [TODO] Optional, informative only (Q6: frost heating accepted). Verification of H1 (owner + agent, read-only via ha-mcp / history): one night with
   outdoor < 3 °C, house ~22 °C, TDL 20, Loxone warm enough (mode `off`). Compare
   `sensor.geotherm_heating_circuit_flow_temp_desired` with the heating curve (0.15) at room
   setpoint TDL 20 vs at the actual room temperature; also watch
   `sensor.geotherm_heating_energy_integral` (`ehp/Integral`),
   `binary_sensor.geotherm_heating_compressor_running` (`ehp/Comp`),
   `sensor.geotherm_heating_circuit_flow_temp` and `binary_sensor.geotherm_heating_circuit_pump`
   (`ehp/Hc1Pump`). Optional cross-check: change TDL by 1 K at the panel and see whether the flow
   setpoint moves while the room stays ~22 °C. Record only a confirmed result via
   `record-learning`.

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

## Owner decisions (2026-11-14)

- **Q1** Helper 18–24 °C, step 0.5: yes.
- **Q2** Keep the `+ 1`: in-season target = comfort + 1.
- **Q3** Remove the TDL sensor entirely.
- **Q4** No default (no `initial:`); owner sets the helper to 21 by hand after deploy.
- **Q5** TDL floor value does not matter to HA (panel setting, no logic).
- **Q6** Frost-protection heating while Loxone says warm enough: accepted, ignore it.
- **Q7** Yes: fix the stale README "Mode law" bullet (`auto` normally …, predates the on/off law
  of #169) in step 7.
- **Q8** No relabel of the HVAC action row.

## Status

Phase A done; awaiting approval of Phase B. All owner questions answered.

Phase A result: helper added; target derives from it (no `availability:`); writer gates only on
the target; TDL sensor, poll line and group entry removed; notification shows comfort; boost-offset
comment corrected. `ci-local.sh --yaml` passes. `--package heating_pv_boost`: 26 passed, 11 failed,
all in Phase B scope (TDL rows / poll count 20 / helper not seeded / TDL-derived expectations):
`test_expire_after`, `test_target_temp`, `test_ebusd_registers`, `test_ebusd_poll_registration`,
and 7 comfort tests (table, ebusd offline, mode hold, stale read-back, Loxone silent, warm_enough
unknown, hold ends while disarmed).

- [DONE] 1–4 Phase A (code)
- [TODO] 5 Phase B (tests)
- [TODO] 6–7 Phase C (docs, dashboard, cross-refs)
- [TODO] 8–9 Phase D (owner deploy, verification)
- [TODO] 10 Close
