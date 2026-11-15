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

- Files (what each covers: its module docstring): `tests/ha/test_heating_pv_boost.py`
  (formulas, interlock, slab decision, run statistics, meters), `_comfort.py` (Phase 2,
  `doc/heating_pv_boost/design.md#HPB-1` rows 1-7), `_ebusd_registers.py` (every ebusd payload,
  the live `/get` priorities), `_rolling.py` (30-day `sql` on a standalone SQLite),
  `tests/e2e/test_restart.py` (daily meter across a real restart); `warm_enough` in
  `tests/ha/test_energy_loxone.py`, the ebusd registers' missing `expire_after` in
  `tests/ha/test_energy_expire_after.py`.
- Text sensors (`hvac_action` etc.) store an empty render as `''`; the rule is in the `ha-mqtt`
  skill.
- The Shelly Pro 3EM entities get their production ids on a fresh registry; other MQTT ids may
  not (#146).
- CONFIRMED (`test_slab_mode_wanted_delays`): `heating_slab_mode_wanted` (delay_off 20 min) is
  `unknown` after boot until the delay elapses; the control law counts it as off.
