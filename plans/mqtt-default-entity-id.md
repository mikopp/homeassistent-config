# Plan: pin MQTT sensor entity IDs with `default_entity_id`

## Status
- [x] Problem found (in-process test spike, `plans/test-execution.md` Step 0 results, finding 1)
- [ ] Step 1 research: real IDs via ha-mcp and source check, awaiting approval
- [ ] Step 2 YAML change, awaiting approval
- [ ] Step 3 tests and deploy note

Deferred by the owner: fix it another time. Tracked in GitHub issue #146.

## Problem (CONFIRMED by the in-process spike, HA 2026.10.4)
- **How HA picks an ID.** HA gives an entity its ID once, at first registration, and stores it in `.storage`. Later YAML changes do not move it. Without `default_entity_id:`, HA builds the ID from area + device + entity name (`.claude/rules/ha-yaml.md`).
- **Which sensors.** Most MQTT sensors in `packages/victron.yaml` and all in `packages/energy.yaml` have no `default_entity_id`. `packages/heating_pv_boost.yaml` (ebusd) has not been checked.
- **What a fresh registry gives:**

  | Fresh registry gives | Config reads |
  |---|---|
  | `sensor.electrical_victron_energy_system_victron_grid_l1_power` | `sensor.victron_grid_l1_power` |
  | `sensor.pool_pool_pump_pool_pump_power` | `sensor.pool_pump_power` (assumed from the Docker tests' seeds, unverified) |

- **Why production still works.** The live registry holds the short IDs, which were apparently registered before the device and area existed.
- **When it breaks.** The whole Victron template chain (grid total, battery residual, energy accumulators, Energy Dashboard sources) shows unavailable whenever these entities are registered again:
  - a restore without `.storage`, or a new instance;
  - deleting and re-adding an entity, or an MQTT reset;
  - a new MQTT sensor on the same device, which gets the long form straight away.
- **Why the current tests do not show it.** The Docker suite seeds states under the short IDs. The in-process spike works around it by pre-registering the production IDs (`tests/ha/conftest.py`, `_victron_mqtt_unique_ids`).

## Step 1 – Research (read-only)
1. Read the `FROM` line of `.github/ha-versions/ha/Dockerfile`, and the `ha-mqtt` skill (default_entity_id vs UI rename).
2. Confirm in HA source at the pinned tag (`helpers/entity_platform.py`, `helpers/entity_registry.py`, MQTT entity setup) that `default_entity_id` is used only at first registration. An existing registry entry must keep its ID and history.
3. List every MQTT sensor without `default_entity_id` in `victron.yaml`, `energy.yaml` and `heating_pv_boost.yaml`.
4. For each one, look up the live entity ID via ha-mcp by `unique_id` (read-only). Never derive an ID. An ID renamed in the UI stays as the registry has it; note it.

## Step 2 – YAML change
- Add `default_entity_id: <live id>` to each sensor found in Step 1, with a one-line comment per block pointing here (or to the package note).
- Run `.github/scripts/ci-local.sh` and `check_config`.

## Step 3 – Tests and deploy
- Remove the pre-registration stand-in from `tests/ha/conftest.py`. The in-process tests must still pass with a fresh registry, which proves the fix.
- Look the Shelly IDs in the tests up by `unique_id`, or use the now-pinned IDs.
- Deploy note, from `git diff origin/master...HEAD`: `git pull` and a YAML reload or restart. No ID or history change is expected on the live system, as confirmed in Step 1.2.
- Record the learning via `record-learning` once it is CONFIRMED. Delete this plan when done.
