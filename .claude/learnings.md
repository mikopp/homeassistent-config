# Project Learnings & Gotchas

Evidence grading is explicit throughout. **CONFIRMED** = a stack trace, a source read at the pinned
pinned HA version (`.github/ha-versions/ha/Dockerfile`), or a deterministic reproduction. **OBSERVED** = real data from a real run, but with a
plausible alternative explanation still open. **UNPROVEN** = a hypothesis kept only so it is not
re-litigated from scratch. Never promote an entry a grade without new evidence. See `CLAUDE.md` →
"NEVER write an unconfirmed learning".

Topic knowledge lives in project skills (`.claude/skills/`): `ha-templates`, `ha-energy-metering`,
`ha-mqtt`, `ha-test-harness`. Package-specific facts live in `packages/notes/<package>.md`.

## Active Patterns

### Home Assistant
- **Verifying HA-version-specific behaviour**: pull the actual source at the pinned version (Dockerfile `FROM`, not `.HA_VERSION`, which is gone) —
  `gh api repos/home-assistant/core/contents/<path>?ref=<tag>`. This is what CLAUDE.md's "HA version
  gate" operationalises, and it is what turned three of the entries on this page from guesses into
  facts. Docs were ambiguous or silent every time it mattered.

## Log

### 2026-08-16 — Victron AC-referenced solar/battery accounting (PR #101)
- **Task:** Rewrote `packages/victron.yaml` so Solar and Battery are AC-referenced, then spent the
  rest of the session on the CI fallout.
- **Learning:** Production YAML landed well (state-only baseline sensors, `platform: integration`
  for grid, explicit conversion-loss diagnostics). The debugging around it produced **three
  successive confident root-cause claims that were each wrong**, all in the same way: a plausible
  mechanism fitted to a single confirming CI run. In order — custom `attributes:` being broken in
  HA; dropping a `jump_to_next` alignment call causing a hang; pergola year-jumps causing the hang.
  Two had to be deleted from this file as false positives. `CLAUDE.md` now forbids writing a
  learning without confirmed evidence, and this file grades every entry.

### 2026-08-16 (follow-up) — grid import/export accuracy
- **Task:** Switched `victron_grid_energy_import`/`_export` from 1/min sampling to
  `sensor: platform: integration`; added `recorder: purge_keep_days: 5`.
- **Learning:** `platform: integration` has sharp edges not in the docs: rejects
  `device_class`/`state_class`; keeps its total in entity memory (immune to `set_state()` resets);
  has no timer without `max_sub_interval`, so it bills the entire gap since the last source event as
  one trapezoid; and it listens to state *reports* as well as changes.

### 2026-08-16 (follow-up) — the hang, actually diagnosed
- **Task:** Stopped theorising, instrumented instead.
- **Learning:** `pytest-timeout --timeout=90 --timeout-method=thread` named the blocking line on the
  first try: `requests.get` with no `timeout=`, parked in `socket.recv_into`. HA accepts the
  connection and never answers; the HA-side reason is still unknown, but the test side is now
  bounded by a `requests` wrapper in `tests/conftest.py`. Two follow-on regressions, both caught and
  both instructive: pytest-timeout charges session-fixture setup to the first test (fixed with
  `timeout_func_only`), and the airflow reload helper's clock jump was secretly supplying the delay
  crossing that two other tests depended on. Also cut ~11 days of pointless mocked-clock travel out
  of `test_victron.py` by replacing 20 `jump_to_next(hour=...)` calls with 11 `fast_forward` calls.

### 2026-10-14 — heating/cooling indicator thresholds + pergola season sync (PR #123)
- **Task:** Made the indicator thresholds settings and synced `pergola_heating` from the indicator;
  CI stayed red after a first "race-free tests" fix.
- **Learning:** Both remaining failures were HA semantics, not timing: a `this`-reading template
  re-renders itself after an external `set_state()` and walks its hysteresis back toward its inputs,
  and `automation.trigger` skips conditions unless `skip_condition: false`. Tests now drive the 48h
  mean and assert the indicator's real state; the sync automation names both seasons explicitly
  with no `default:`.

### 2026-10-23 — airflow: `sensor.airflow_cooling_state` as the single decision
- **Task:** Active heating showed `free_cooling`: the controller had no block for heating + free
  cooling (stuck `cool`), and Section 2 raised the rate on raw `free_cooling_available`.
- **Learning:** Root cause was structural — five consumers read the indicators directly, each with
  its own season rules. Moved all priority/season logic into one stateless decision (macro in
  `custom_templates/airflow_decision.jinja`); controller, boost and hvac_action read only it. The
  stuck-profile recovery blocks disappeared with the "keep current profile" path.
