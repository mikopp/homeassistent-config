# Energy: verify live entity ids

**Status:** PLAN ONLY. Each step needs explicit approval (root CLAUDE rules 2-5).
Needs an agent with the **ha-mcp** connection, used **read-only**: lookups only, no writes and no
service calls (root `CLAUDE.md` "MCP usage").

## Status
- Knowledge dedup of `packages/energy.yaml` is done. The entity map is in `doc/energy/notes.md`
  under "Entity map".
- Those MQTT sensors have **no `default_entity_id`**, so their ids cannot be derived
  (`.claude/rules/ha-yaml.md` "Entity IDs"). The dedup session had no ha-mcp, so the live ids
  are still unverified:
  - **Confirmed by use:** `sensor.technikraum_heizung_heizung_power`. It is referenced by
    `packages/heating_pv_boost.yaml` and `dashboards/heating-dashboard.yaml:134`.
  - **Unverified:** `sensor.technikraum_heizung_heizung_energy`. It is the `source:` of
    `heating_electricity_daily` (`packages/heating_pv_boost.yaml:537`), and the YAML comment there
    says "verify it after deploy".
  - **Unverified:** the pool pump ids `sensor.pool_pump_*` and `binary_sensor.pool_pump_switch`.
    The in-process tests no longer use them: they find the sensors by unique_id (#146).
  - **Unknown:** all rain water pump and Loxone (washer, tumble dryer, dishwasher) ids.
  - **To re-check:** the go-e source ids `sensor.go_echarger_homekopp_power_total` and
    `sensor.go_echarger_homekopp_total_energy_charged`. They can change on a re-pair.
  - The wallbox wrappers `sensor.wallbox_power` and `sensor.wallbox_energy` are template entities
    without a device. Confirm them too.

## Steps
1. [TODO] Read the pinned HA version (the `FROM` line of `.github/ha-versions/ha/Dockerfile`) and
   the live version (`ha_get_system_health`). Note any difference.
2. [TODO] For each `unique_id` in `packages/energy.yaml`, look up the live entity with
   `ha_get_entity(unique_id="<unique_id>")`. There are 18 MQTT ids (`shelly_pool_pump_*`,
   `shelly_rainwater_pump_*`, `shelly_pro3em_heizung_*`, `loxone_*`) plus `wallbox_power` and
   `wallbox_energy`. Also check that both go-e source entities exist and record their
   `unit_of_measurement` and `state_class`, which the note claims. Record entity_id, state and
   unit in a table in this plan.
3. [TODO] Update the "Entity map" in `doc/energy/notes.md` with the confirmed ids. Drop the
   "unverified" / "not live-verified" marks only for ids that were looked up. Mark any id that
   is not found as such.
4. [TODO] If any live id differs from a reference in the repo, fix the reference and say so:
   - `packages/heating_pv_boost.yaml:537`, and remove its "verify it after deploy" comment once
     the id is confirmed
   - `tests/conftest.py`
   - `tests/ha/test_energy_wallbox.py`
   - `tests/ha/test_energy_pool_pump.py`
   - dashboards

   A changed reference in YAML or tests is a behaviour change. It needs CI green, not only
   `yaml_semantic_equal.py`.
5. [TODO] Verify:
   - `.github/scripts/ci-local.sh`
   - `git ls-files --eol` shows no CRLF
   - CI is green
   - deploy/migration notes are derived from `git diff origin/master...HEAD`

   Delete this plan in the PR's last commit.
6. [TODO] Close: distil the confirmed ids into `doc/energy/notes.md`, drop any story to background, update pointers, delete this plan (`doc/KNOWLEDGE.md#K-6`)
