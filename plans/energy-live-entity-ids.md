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
    `packages/heating_pv_boost.yaml` and `dashboards/heating-dashboard.yaml:228`.
  - **Unverified:** `sensor.technikraum_heizung_heizung_energy`. It is the `source:` of
    `heating_electricity_daily` and `heating_electricity_by_mode` (`packages/heating_pv_boost.yaml`,
    `source: sensor.technikraum_heizung_heizung_energy`), and the YAML comment above the first
    says "verify it after deploy".
  - **Unverified:** the pool pump ids `sensor.pool_pump_*` and `binary_sensor.pool_pump_switch`.
    The in-process tests no longer use them: they find the sensors by unique_id (#146).
  - **Unknown:** all rain water pump and Loxone (washer, tumble dryer, dishwasher) ids.
  - **To re-check:** the go-e source ids `sensor.go_echarger_homekopp_power_total` and
    `sensor.go_echarger_homekopp_total_energy_charged`. They can change on a re-pair.
  - The wallbox wrappers `sensor.wallbox_power` and `sensor.wallbox_energy` are template entities
    without a device. Confirm them too.
- **OBSERVED live (2026-11-15, read-only ha-mcp `render_template`, one reading each):**

  | Entity | Exists | Unit | `state_class` | `device_class` |
  |---|---|---|---|---|
  | `sensor.go_echarger_homekopp_power_total` | yes | W | none | power |
  | `sensor.go_echarger_homekopp_total_energy_charged` | yes | Wh | `total_increasing` | energy |
  | `sensor.kitchen_dishwasher_dishwasher_energy` | yes | kWh | `total_increasing` | energy |

  - Both go-e source ids exist under the names the repo uses. Step 2 can start from them.
  - **UNPROVEN:** that `sensor.kitchen_dishwasher_dishwasher_energy` is the entity of unique_id
    `loxone_dishwasher_energy`. Its name fits the area + device + name pattern and its unit fits
    the Loxone energy sensor, but `render_template` does not show the unique_id. Step 2's
    `ha_get_entity(unique_id=...)` settles it.
- **Test seeds are the inverse of production (OBSERVED, repo at #173):** the
  `sensor.go_echarger_homekopp_*` seeds in `tests/baseline.py` give the go-e power source
  `state_class: measurement` and the energy source **no** `state_class`. Live it is the other way
  round (table above). The test stays useful (the wrapper must work without a source
  `state_class`); the open question is whether the baseline seed and its comment should mirror
  production. Work item: step 4.
  - **UNPROVEN:** why it changed (go-e firmware or discovery update). One live reading does not
    show whether the energy source ever lacked `state_class`.
  - **UNPROVEN:** that the go-e source can declare kW / kWh. Live declares W / Wh; no source shows
    kW. The kW / kWh cases in `tests/ha/test_energy_wallbox.py` stay as coverage for a replacement
    source.

## Steps
1. [TODO] Read the pinned HA version (the `FROM` line of `.github/ha-versions/ha/Dockerfile`) and
   the live version (`ha_get_system_health`). Note any difference.
2. [TODO] For each `unique_id` in `packages/energy.yaml`, look up the live entity with
   `ha_get_entity(unique_id="<unique_id>")`. There are 18 MQTT ids (`shelly_pool_pump_*`,
   `shelly_rainwater_pump_*`, `shelly_pro3em_heizung_*`, `loxone_*`) plus `wallbox_power` and
   `wallbox_energy`. Also check that both go-e source entities exist and record their
   `unit_of_measurement` and `state_class`. A first reading is in the Status section; re-read
   them here so the table holds one consistent lookup. Record entity_id, state and unit in a
   table in this plan.
3. [TODO] Update the "Entity map" in `doc/energy/notes.md` with the confirmed ids. Drop the
   "unverified" / "not live-verified" marks only for ids that were looked up. Mark any id that
   is not found as such.
4. [TODO] If any live id differs from a reference in the repo, fix the reference and say so:
   - `packages/heating_pv_boost.yaml`: both `source: sensor.technikraum_heizung_heizung_energy`
     meters and the `statistic_id IN ('sensor.technikraum_heizung_heizung_energy')` query; remove
     the "verify it after deploy" comment once the id is confirmed
   - `tests/baseline.py` (go-e seeds)
   - `tests/ha/conftest.py` (`sensor.go_echarger_` prefix, `:364`)
   - `tests/e2e/conftest.py:163` and `tests/e2e/test_restart.py:47` (Heizung energy id)
   - `tests/ha/test_energy_wallbox.py`
   - `tests/ha/test_energy_pool_pump.py`
   - dashboards

   Independent of any id change, align the go-e seeds with the live attributes from step 2:
   - the `sensor.go_echarger_homekopp_*` seeds in `tests/baseline.py`: decide with the owner whether the seeds mirror production
     (power without `state_class`, energy with `total_increasing`) or stay as the worst case. In
     both cases the comment there must say which one it is.
   - `tests/ha/test_energy_wallbox.py`: if the baseline seed mirrors production, keep the
     `_energy()` helper without `state_class`, so the wrapper still proves it supplies
     `total_increasing` itself. Check that its docstrings still match the seeds.

   A changed reference in YAML or tests is a behaviour change. It needs CI green, not only
   `yaml_semantic_equal.py`.
5. [TODO] Verify:
   - `.github/scripts/ci-local.sh`
   - `git ls-files --eol` shows no CRLF
   - CI is green
   - deploy/migration notes are derived from `git diff origin/master...HEAD`

   Delete this plan in the PR's last commit.
6. [TODO] Close: distil the confirmed ids into `doc/energy/notes.md`, drop any story to background, update pointers, delete this plan (`doc/KNOWLEDGE.md#K-6`)
