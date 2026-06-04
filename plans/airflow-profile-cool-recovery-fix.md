# Airflow Profile — Fix the "stuck-`cool`" trap (Block 4 bypass-close recovery)

## Problem

Profile recovery to `comfort` is **Block 3** of Section 1 in `airflow_ventilation_controller`,
gated on `dew_min ≤ indoor_dew ≤ dew_max` (BAND). The warm/retain block (**Block 1A**) is
**excluded in cooling season**. So when indoor dew sits **outside** the band and no owner
(`free`/`flush`) is active, *no profile block matches → `default: []` no-op → profile freezes at
its last value*. The harmful frozen value is `cool` (bypass open).

### Reachable traps (from architecture §11.5 "keep" rows)

| Trap | Season | free | flush | dew | Result today | Why no block matches |
|------|--------|------|-------|-----|--------------|----------------------|
| C7 (overcool) | COOL | – | – | DRY | stuck `cool`, keeps overcooling, state reports `cooling` | 1A excluded (cooling); 3 band-fail (DRY) |
| C8 (humid) | COOL | – | – | HUM | stuck `cool`, bypass open imports humid air while `low` preset "protects" | 1A needs DRY; 3 band-fail (HUM) |
| N3 (humid) | NEUT | – | – | HUM | stuck `cool`, same conflict | 1A needs DRY; 3 band-fail (HUM) |

The humid traps are worst: bypass stays open during a humid spell — exactly when it should close
for heat-recovery — and `low` preset only reduces the *rate* of humid import, not the open bypass.
Self-reinforcing: open bypass + humid outdoor → dew won't fall into band → stays `cool`.

Root cause: Block 3 can only close the bypass when dew is already in `[min,max]`, and 1A won't
rescue in cooling season. `default: []` (chosen to avoid oscillating against 1A's warm) also blocks
the legitimate `cool → comfort` close.

## Fix — new **Block 4** (bypass-close recovery), inserted after Block 3, before `default`

Close the bypass to `comfort` whenever the profile is **currently `cool`** but **no owner wants
cool** and it is **not heating season**:

```
- conditions:
    - profile == cool          # only the trap value; warm/comfort are never stuck
    - free  == off
    - flush == off
    - season != active_heating # heating is owned by Block 1B (sets warm first)
  sequence:
    - select.select_option comfort
    - notify (bypass closed — cool no longer warranted)
```

### Why this is safe (no oscillation, no over-fire)

- **Requires `profile == cool`.** Once any earlier block flips the profile away from `cool`, Block 4
  is inert. So it cannot ping-pong against Block 1 or Block 3:
  - NEUT + DRY + cool: **Block 1A** runs first → sets `warm` → Block 4 inert. (Intended: dry neutral
    air → warm/retain, not comfort.)
  - HEAT + cool + free–/flush–: **Block 1B** runs first → sets `warm` → Block 4 inert. (Season guard
    is belt-and-suspenders.)
- **Requires `free– AND flush–`.** Any legit cool (free cooling / flush) keeps `free` or `flush` on,
  so Block 2 holds `cool` and Block 4 is suppressed. Block 4 only ever fires for the no-owner trap.
- **In-band cases** (free–/flush–, dew BAND) are already handled by Block 3 (which runs first); Block 4
  uniquely covers the out-of-band DRY/HUM traps.
- **`low` is irrelevant to Block 4.** When `low` is on (humid trap) Section 2 sets the `low` preset;
  Block 4 independently closes the bypass → result is `comfort` profile + `low` preset = correct
  moisture protection (closed bypass + reduced rate), replacing the stuck-`cool` conflict.

### Trap outcomes after fix

| Trap | New Profile | Preset | action | cooling_state |
|------|-------------|--------|--------|---------------|
| C7 | comfort | auto on (restore) | fan | comfort |
| C8 | comfort | low | fan | moisture_protection |
| N3 | comfort | low | fan | moisture_protection |

## Scope

Single file: `packages/airflow_cooling.yaml` — add Block 4 to Section 1 `choose:` of
`automation.airflow_ventilation_controller`, immediately after Block 3 and before `default: []`.

No change to: sensors, binary sensors, Section 2, boost automation, helpers, group, climate.

## Tests — `tests/test_airflow.py`

**Harness limit (documented in the file header):** `select.comfoconnect_pro_temperature_profile`
is a bare REST stub — `select.select_option` writes are silently ignored. A `cool → comfort` *write*
is therefore **not observable** in CI; definitive behavioural confirmation is post-deploy
(`ha_get_state`). CI tests verify: (a) the new Block 4 path executes **trace-clean** for each trap
(catches template/entity/condition errors), and (b) **regressions** — Block 4 does NOT over-fire on
legit cool.

New tests to add:

1. `test_controller_cool_recovery_dry_cooling_season_trace` (C7) — auto on; profile=cool; season
   active_cooling; free off; flush off; low off; `airflow_min_indoor_dew_5min`=7.0 (DRY, < dew_min
   9.08). `_trigger`. Trace-clean (Block 4 fires; write ignored on stub). Comment: post-deploy →
   comfort.

2. `test_controller_cool_recovery_humid_neutral_trace` (N3) — auto on; profile=cool; season neutral;
   free off; flush off; low on; `airflow_min_indoor_dew_5min`=14.0 (HUM, > dew_max 12.09). `_trigger`.
   Trace-clean. Comment: post-deploy → comfort + low preset.

3. `test_controller_cool_recovery_humid_cooling_trace` (C8) — as #2 but season active_cooling.

4. `test_controller_no_recovery_when_flush_on` (regression) — profile=cool; free off; flush **on**;
   season active_cooling. `_trigger`. assert profile stays `cool` (Block 2B holds; Block 4 suppressed
   by `flush`). Observable (cool→cool idempotent).

5. `test_controller_no_recovery_when_free_on` (regression) — profile=cool; free **on**; flush off;
   season active_cooling. `_trigger`. assert profile stays `cool` (Block 2A holds; Block 4 suppressed
   by `free`). Observable.

6. `test_controller_no_recovery_in_heating` (regression) — profile=cool; season active_heating; free
   off; flush off. `_trigger`. Trace-clean. Comment: Block 1B owns this → warm (write ignored on
   stub); Block 4 season-guarded off.

(Existing `test_airflow_humidity_in_dead_band_neutral_comfort` already covers the Block 3 in-band
path — unchanged.)

## Doc update — `plans/airflow-cooling-architecture.md`

After implementation, update:
- **§11.5** rows C7, N3, C8: Profile `keep` → `comfort (4)`; fill action/state per the table above;
  drop note 1's C7/N3/C8 references (only H6 remains a true `keep`).
- **§11.3** profile table: add Block 4 row `comfort | profile=cool AND free– AND flush– AND season≠HEAT`.
- **§10** anti-flip-flop: add row "Block 4 bypass-close recovery | profile automation | drains
  stuck-`cool` when no owner; gated `profile==cool` so it can't oscillate vs Block 1".

## Verification

1. `python -m py_compile` / `yaml.safe_load` on the package — parses clean.
2. CI: 6 new tests pass (trace-clean + 2 observable regressions) alongside the existing suite.
3. Post-deploy (user `git pull` + reload): drive a trap (e.g. let free cooling overdry, or wait for
   a humid spell with flush cleared) and confirm `select.comfoconnect_pro_temperature_profile`
   transitions `cool → comfort` and the bypass closes.

## Status
- [x] Add Block 4 to Section 1 `choose` in `packages/airflow_cooling.yaml`
- [x] Add 6 trap/regression tests to `tests/test_airflow.py`
- [x] YAML parses clean (`yaml.safe_load`)
- [x] Update `plans/airflow-cooling-architecture.md` §10, §11.3, §11.5
