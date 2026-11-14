---
paths:
  - "tests/ha/test_heating_pv_boost.py"
  - "tests/ha/test_heating_pv_boost_comfort.py"
  - "tests/ha/test_heating_pv_boost_ebusd_registers.py"
  - "tests/ha/test_heating_pv_boost_rolling.py"
  - "tests/e2e/test_restart.py"
---
# heating_pv_boost tests

Package-specific test facts for `packages/heating_pv_boost.yaml`; package facts:
`doc/heating_pv_boost/notes.md`; generic harness knowledge: the `ha-test-harness` skill.

In-process (`tests/ha/test_heating_pv_boost.py`, real broker, ebusd/Shelly/Victron payloads):
surplus, compressor and cycling formulas, cooling interlock, derived setpoint (case tables), and
on a frozen clock the DHW mask (delay_off), the slab decision (delay_on/off, master switch,
Schmitt), the last run, the real history_stats (recorder; a `history_stats.reload` test proves the values are read back from the
recorded history) and the daily meters' midnight reset.
MQTT-fed inputs (ebusd strings by name and raw enum number, Shelly Pro 3EM JSON, Venus values) go
only over the real broker; "unavailable" is a real `expire_after`. The daily meters are the real
`utility_meter`s; the 48h mean (which drives the real season indicator) and the η accumulators'
inputs outside the clock tests are seeded, and so is the comfort helper in the setpoint table. `tests/e2e/test_restart.py` checks that the
`heating_electricity_daily` meter survives a real restart. The Shelly Pro 3EM entities get their
production ids on a fresh registry; other MQTT ids may not (#146).
`tests/ha/test_heating_pv_boost_ebusd_registers.py` feeds every ebusd-fed entity its live payload
and variants (enum names and raw numbers, case, unmapped, short, empty, garbage) and fails on any
mqtt WARNING (`ehp/Integral`, the harness sync channel, has its own test). Its poll test asserts
that every trigger of `heating_ebusd_poll_registration` sends exactly the 19 `/get` priorities
seen on the live broker, and nothing while the scan reads `running`. The ebusd registers have
no `expire_after`: `tests/ha/test_energy_expire_after.py` holds their value for a
week (`ebusd/global/running` is `true`/`false`, `scan` is `finished` when done: owner). `loxone/heating/warm_enough`
is fed by `tests/ha/test_energy_loxone.py`: an empty or garbage payload renders OFF ("not warm
enough"), by design (owner): the template has no empty guard. A payload without
field 3 renders `heating_hvac_action` as `unknown`: a sensor without `device_class`/unit stores an
empty render as `''` (only numeric sensors ignore it, source read at 2026.10.4). The energy mode is a case table; the per-mode meters,
`heating_energy_meters_follow_mode` and both efficiencies are tested end to end (`test_energy_split_by_mode`).
The meters' mode selects make the real `select` domain load, so `tests/ha/conftest.py` wraps the real
`select.select_option` and records only calls to external entities (ComfoConnect).
`tests/ha/test_heating_pv_boost_rolling.py`: the 30-day `sql` queries, rendered from the config, run
on a standalone SQLite with fabricated rows (window edge, id lists, partial history, empty → 0), the
30d efficiency table (floor → `unknown`, missing input → `unavailable`) and a clean `sql` load; no HA
long-term statistics (owner).

`tests/ha/test_heating_pv_boost_comfort.py` (Phase 2): the control-law rows 1-7 as a table (real
indicator via the seeded 48h mean, slab seeded, read-backs, ehp/Status and Loxone over the broker),
armed last so one evaluation is asserted; HA's own `test/fence` message proves "no write". Own
tests: master switch off, idempotence (raw enum read-back), ebusd offline then back,
the 30 min hold (deferred mode, immediate setpoint, new hold after the write), a hold that ends
while disarmed (arming applies it), a never-echoing read-back (no mode re-send inside the hold, no
setpoint re-send inside 5 min), Loxone silent 24 h (expires to `unavailable`; an identical re-sent
payload restarts the expiry),
and `warm_enough` unknown / unavailable (heats).

CONFIRMED: `heating_slab_mode_wanted` (delay_off 20 min) is `unknown` after boot until the delay
elapses.
