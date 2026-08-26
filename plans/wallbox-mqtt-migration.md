# Wallbox energy/power — migrate evcc → go-e MQTT, behind a stable abstraction

## Context

The Energy Dashboard's wallbox figures currently come from two raw MQTT sensors defined in
`packages/energy.yaml:143-171`, fed by evcc's loadpoint topics:

- `sensor.evcc_loadpoint_1_charge_power` ← `evcc/loadpoints/1/chargePower`
- `sensor.evcc_loadpoint_1_charge_energy` ← `evcc/loadpoints/1/chargeTotalImport`

evcc republishes these too slowly to be useful — readings lag the actual charge session. The
go-e charger has since been added directly to HA via its firmware's MQTT auto-discovery
(`homeassistant/<domain>/go-e_291401/…`, data topics `go-eCharger/<key>`), which publishes at the
charger's own much faster cadence.

Two problems to solve, not one:

1. **Swap the source.** Take wallbox power/energy from the go-e discovery entities instead of evcc.
2. **Stop the source from leaking into the Energy Dashboard.** Today the dashboard points straight at
   a vendor-named entity id, so every source change means renaming entities (to keep history) and
   re-picking sources in the UI. From now on the dashboard points at neutral ids
   (`sensor.wallbox_power`, `sensor.wallbox_energy`) whose definition names the source in exactly one
   place in YAML. A future source swap becomes a one-line edit — no entity renames, no dashboard edit.

A one-time Energy Dashboard change and a history break are accepted for *this* migration (confirmed
by the user); the point is that it is the last one. See **History impact** below for exactly what
"break" means here — it is narrower than it sounds.

### Why a `template:` wrapper and not raw `mqtt:` sensors

Chosen deliberately (user-confirmed): a template sensor can wrap **any** future source — MQTT, REST,
a cloud integration, another wallbox. An `mqtt:` sensor could only ever be repointed at another MQTT
topic, which would bind the stable id to MQTT forever. The repo already has this exact pattern
documented: `packages/pergola.yaml:275-302` ("Thin wrapper around the raw Victron solar charger
output… if the underlying sensor ID ever changes, only this sensor needs updating").

There is a second, independent reason the wrapper is required: the go-e firmware's discovery payload
for `total_energy_charged` is [known to omit `state_class: total_increasing`](https://github.com/goecharger/go-eCharger-API-v2/issues/241),
so that entity **cannot be selected in the Energy Dashboard at all**. The wrapper supplies the
missing `state_class`.

### History impact

Long-term statistics live in the recorder DB (`statistics` / `statistics_meta`), keyed by
`statistic_id` — for a sensor, its entity id string. `.storage/energy` is only a *list of
statistic_ids*; editing that list never touches stored data. Therefore:

- **Nothing is deleted.** All accumulated `sensor.evcc_loadpoint_1_charge_energy` history stays in
  the DB and remains viewable in Developer Tools → Statistics and in history/statistics cards.
- **Totals are unaffected.** Grid import and total house consumption come from the Victron sensors;
  the wallbox is an *individual device* breakdown, not an energy source. (Assumption to confirm on
  the host: the wallbox is configured under "Individual devices". If it sits in another slot, this
  section needs revisiting.)
- **Going forward**, `sensor.wallbox_energy` starts a fresh series. `eto` is a large lifetime counter
  and `total_increasing` baselines on the first observed value, so there is no false spike at
  cut-over.
- **The one visible loss**: viewing a *past* period on the Energy Dashboard shows no wallbox row,
  because the dashboard only queries currently-configured statistic_ids.

To avoid even that loss: **add** `sensor.wallbox_energy` and **leave**
`sensor.evcc_loadpoint_1_charge_energy` in the individual-devices list. Historical statistics render
fine for a statistic_id whose entity no longer exists — past periods keep the evcc row while the new
wallbox row grows from cut-over. Cost is one dead row in the device list. This is the default
recommendation; drop the old entry later once the history no longer matters.

**Explicitly rejected:** merging both into one continuous series by UI-renaming the old entity to
`sensor.wallbox_energy` before deploy. It is order-dependent and fragile (the template sensor lands
on `sensor.wallbox_energy_2` if the orphaned registry entry is not cleared first), and it is unsafe:
evcc's `chargeTotalImport` and go-e's `eto` have different absolute baselines, so if `eto` is the
larger of the two, `total_increasing` books the difference as real consumption — a one-time spike of
potentially thousands of kWh. Two separate series is correct.

### Unit handling

go-e's API v2 publishes `nrg[11]` in **W** and `eto` in **Wh** (confirmed against
[`syssi/homeassistant-goecharger-mqtt`'s sensor definitions](https://github.com/syssi/homeassistant-goecharger-mqtt/blob/main/custom_components/goecharger_mqtt/definitions/sensor.py)
— `eto`/`wh` → `WATT_HOUR`, `nrg` attr 11 → `WATT`). But the *firmware's own discovery payload* may
apply its own `value_template` and declare kW/kWh instead, and that could not be verified from this
session (no HA access here). Rather than guess, both wrappers **read the source's own
`unit_of_measurement` attribute and normalise** — correct either way, and it also absorbs a future
source that reports in different units. HA keeps `states()` and the `unit_of_measurement` attribute
consistent even when a registry unit override is in play, so this is safe.

---

## Changes

### 1. `packages/energy.yaml` — remove evcc, add the go-e wrapper layer

**a. Delete** the evcc header doc block (lines 12-15) and both evcc MQTT sensor blocks
(lines 143-171, including the `&evcc_loadpoint_1` device anchor — it has no other users).

**b. Replace** the header doc lines with a go-e block describing the new two-layer arrangement:

```yaml
# go-e Charger (Wallbox) — via the charger's own MQTT auto-discovery:
#   Discovery: homeassistant/<domain>/go-e_291401/*   Data: go-eCharger/<key>
#   Source entities (owned by the MQTT integration, ids may change on re-pairing):
#     sensor.go_echarger_homekopp_power_total          ← go-eCharger/nrg  (nrg[11])
#     sensor.go_echarger_homekopp_total_energy_charged ← go-eCharger/eto  (lifetime)
#   The Energy Dashboard never references those directly — see the wallbox
#   template wrappers below.
```

**c. Add** a `template:` section at the end of the file (the file has none today — a package may
carry one; see `packages/victron.yaml:220` for the in-package `template:` precedent):

```yaml
# ── Wallbox abstraction layer ─────────────────────────────────────────────────
# STABLE ENTITY IDS — sensor.wallbox_power / sensor.wallbox_energy.
# These are what the Energy Dashboard, statistics and any future card reference.
# They are deliberately named after the *function* (wallbox), not the device, so
# that swapping the charger or its integration is a one-line change to `state:`
# and `availability:` below — no entity rename, no loss of history, no Energy
# Dashboard edit.
#
# Today's source: the go-e Charger MQTT auto-discovery entities.
# Previously: evcc loadpoint 1 (removed — republished too slowly).
#
# Units are normalised from the source's own unit_of_measurement rather than
# assumed, because the go-e firmware's discovery payload chooses its own units.
template:
  - sensor:

      # Instantaneous charge power. Normalised to W (go-e nrg[11] is natively W,
      # but the discovery payload may declare kW).
      - name: "Wallbox Power"
        unique_id: wallbox_power
        state: >
          {% set src = 'sensor.go_echarger_homekopp_power_total' %}
          {% set unit = state_attr(src, 'unit_of_measurement') %}
          {{ ((states(src) | float * 1000) if unit == 'kW'
              else (states(src) | float)) | round(1) }}
        availability: >
          {{ states('sensor.go_echarger_homekopp_power_total')
             not in ['unavailable', 'unknown'] }}
        unit_of_measurement: "W"
        device_class: power
        state_class: measurement
        icon: mdi:ev-station

      # Lifetime cumulative charged energy — the Energy Dashboard's source of truth.
      # go-e `eto` is a lifetime counter (not per-session) and is natively Wh.
      # state_class is declared HERE because the go-e discovery entity omits it,
      # which is why that entity cannot be picked in the Energy Dashboard itself.
      # total_increasing lets HA absorb a counter reset (charger factory reset).
      - name: "Wallbox Energy"
        unique_id: wallbox_energy
        state: >
          {% set src = 'sensor.go_echarger_homekopp_total_energy_charged' %}
          {% set unit = state_attr(src, 'unit_of_measurement') %}
          {{ ((states(src) | float / 1000) if unit == 'Wh'
              else (states(src) | float)) | round(3) }}
        availability: >
          {{ states('sensor.go_echarger_homekopp_total_energy_charged')
             not in ['unavailable', 'unknown'] }}
        unit_of_measurement: "kWh"
        device_class: energy
        state_class: total_increasing
        icon: mdi:lightning-bolt
```

Conventions honoured (`CLAUDE.MD:57-68`): `availability:` guard on every wrapper; **no**
`| float(default)` inside `state:` since availability already guarantees a numeric source; no
`device:` key (unsupported in template YAML — attach to a device via the UI if wanted).

When the source goes unavailable both wrappers go unavailable rather than reporting `0`. For a
`total_increasing` counter that is the correct behaviour (the dashboard shows a gap and resumes);
`sensor.wallbox_power` is display-only, so an honest `unavailable` beats a fake 0. This differs from
the pergola PV wrapper, which maps stale→0 because a downstream rule depends on `pv == 0`.

### 2. `tests/conftest.py` — seed the go-e source entities

`baseline_states` (from ~line 63) seeds every entity whose integration is absent in CI.
`tests/test_templates.py::test_state_templates_strict` renders every `state:` template standalone and
fails on a sentinel output, so without a seed the new wrappers fail CI. Add alongside the Victron
block:

```python
    # go-e Charger wallbox (MQTT discovery — broker absent in CI). Units match the
    # go-e API v2 native payloads: nrg[11] in W, eto in Wh.
    ha.set_state("sensor.go_echarger_homekopp_power_total", "0",
                 {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"})
    ha.set_state("sensor.go_echarger_homekopp_total_energy_charged", "3500",
                 {"unit_of_measurement": "Wh", "device_class": "energy"})
```

### 3. `tests/test_wallbox.py` — new test file

Follow `tests/test_shelly_pool_pump.py` (same harness API: `ha.set_state(...)` then
`ha.assert_entity_state(entity, predicate, timeout=5)`). Unlike that file, these tests seed the
**source** entity and assert on the **wrapper**, so they genuinely exercise the template:

- `eto = 3500 Wh` → `sensor.wallbox_energy == 3.5`
- source declared in `kWh` (e.g. `3.5`) → `sensor.wallbox_energy == 3.5` (pass-through, no double divide)
- `nrg[11] = 11040 W` → `sensor.wallbox_power == 11040.0`
- source declared in `kW` (e.g. `11.04`) → `sensor.wallbox_power == 11040.0`
- source `unavailable` → `sensor.wallbox_energy` is `unavailable` (availability guard works)

### 4. `README.md` — document `packages/energy.yaml`

The Packages section (README.md:9-41) covers pergola, airflow_cooling, heating_cooling_indicator and
victron but **omits `energy.yaml` entirely**. Add a section for it describing the metered devices
(Shelly plugs, Shelly Pro 3EM, Loxone appliances, go-e wallbox) and, explicitly, the wallbox
abstraction rule: *the Energy Dashboard references `sensor.wallbox_*`, never a vendor entity.*
Add a `test_wallbox.py` row to the Tests table.

### 5. `packages/CLAUDE.md` — record the convention

That file currently only covers `airflow_cooling.yaml`. Add a short `energy.yaml` section stating the
rule so it survives future sessions: **Energy-Dashboard-facing entities are function-named wrappers
(`sensor.wallbox_*`); vendor/integration entities are never referenced by the dashboard directly.**

### 6. `plans/wallbox-mqtt-migration.md`

`CLAUDE.MD:4-8` requires a feature plan file in `plans/` with a status section updated after each
step. Copy this plan there and maintain it during implementation.

---

## Post-deploy steps on the HA host (manual — user deploys via `git pull`)

These cannot be done from YAML and are the accepted one-time cost of this migration:

1. **Energy Dashboard** → Settings → Dashboards → Energy → Individual devices: add **Wallbox Energy**
   (`sensor.wallbox_energy`). **Leave `sensor.evcc_loadpoint_1_charge_energy` in the list** so past
   periods still render its history (see *History impact*); remove it later when that no longer
   matters.
2. **Entity registry**: `sensor.evcc_loadpoint_1_charge_power` becomes orphaned/"restored" after the
   YAML removal — delete it in Settings → Devices & Services → Entities. **Do not delete
   `sensor.evcc_loadpoint_1_charge_energy`** while it is still listed in the Energy Dashboard; leave
   the orphaned entry in place so the statistic_id keeps resolving cleanly.
3. *(optional)* Attach `sensor.wallbox_power` / `sensor.wallbox_energy` to a device via the UI —
   template YAML cannot set `device:`.

If go-e readings still feel slow after this, the remaining knob is on the charger itself (MQTT
publish interval / "publish only on change" in the go-e app) — nothing in this repo affects it.

---

## Verification

1. **Lint**: `yamllint -c .yamllint.yaml packages/energy.yaml` (max line length 200, warning level).
2. **Config check**: the CI job `.github/workflows/ha_check.yaml` runs
   `homeassistant --script check_config` with `fakesecrets.yaml` → `secrets.yaml`. Confirm the new
   `template:` block parses and no dangling `*evcc_loadpoint_1` alias remains
   (`grep -n 'evcc' packages/energy.yaml` must return only the historical note in the header
   comment).
3. **Template rendering**: `python3 .github/scripts/extract_templates.py . > /tmp/templates.json`
   then `pytest tests/test_templates.py` — the two new `state:` templates must render non-sentinel
   values against the conftest seeds.
4. **Behaviour**: `pytest tests/test_wallbox.py` — unit normalisation both ways plus the
   availability guard.
5. **Full suite**: `pytest tests/` (the existing `tests/test_shelly_pool_pump.py` still asserts on
   `sensor.pool_pump_temperature`, an entity deleted in commit `c3534e9` — if that fails it is
   pre-existing, not caused by this change; flag rather than silently fix).
6. **History spot-check on the host**: before touching the Energy Dashboard, note the current value
   of `sensor.evcc_loadpoint_1_charge_energy` and confirm in Developer Tools → Statistics that its
   series is intact. Re-check after the switchover — it must be unchanged. Also confirm total house
   consumption for a past day is identical before and after.
7. **On the host after `git pull` + restart**: Developer Tools → States shows
   `sensor.wallbox_power` in W and `sensor.wallbox_energy` in kWh, both tracking the go-e entities;
   start a charge and confirm `sensor.wallbox_power` moves within seconds (the whole point of the
   migration). Then check the Energy Dashboard picks the wallbox up on the next hourly statistics run.

## Status

- [x] 1. `packages/energy.yaml` — evcc sensors + device anchor removed, go-e header doc written,
      `template:` wrapper block appended. Parses; `yamllint -c .yamllint.yaml` clean.
- [x] 2. `tests/conftest.py` — `baseline_states` seeds `sensor.go_echarger_homekopp_power_total`
      (0 W) and `sensor.go_echarger_homekopp_total_energy_charged` (3500 Wh).
- [x] 3. `tests/test_wallbox.py` — 7 tests: Wh→kWh, kWh pass-through, W pass-through, kW→W, idle 0 W,
      and availability propagation on both wrappers.
- [x] 4. `README.md` — `packages/energy.yaml` section added (it was missing entirely) with the
      wallbox indirection rule; `test_wallbox.py` row added to the Tests table.
- [x] 5. `packages/CLAUDE.md` — new "energy.yaml — Energy Dashboard metering" section recording the
      convention and its corollaries.
- [x] 6. `plans/wallbox-mqtt-migration.md` — this file.
- [ ] 7. Commit + push to `claude/wallbox-mqtt-migration-aknw53`
- [ ] 8. **User**: deploy via `git pull` on the HA host, then the manual post-deploy steps above.

### Checks run locally
- `yamllint -c .yamllint.yaml packages/energy.yaml` → clean.
- YAML parses; `template:` yields exactly `Wallbox Power` (W, measurement) and `Wallbox Energy`
  (kWh, total_increasing); 16 mqtt sensors remain (was 18).
- `extract_templates.py` classifies all four new templates as **state_templates** (strict mode), and
  each renders non-sentinel against the conftest seeds: `0.0`, `True`, `3.5`, `True`.
- Unit-normalisation logic verified against a standalone Jinja2 environment for all six
  value/unit combinations.

### Not runnable in this environment
`homeassistant --script check_config` and `pytest tests/` need the HA container and the
`ha_integration_test_harness` package; both run in the `ha_check.yaml` CI job on push.
