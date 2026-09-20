# ebusd PV Heating Optimisation — slab pre-charging from PV surplus

## Context

The house has a Vaillant geoTHERM brine-to-water heat pump on ebus, a Victron PV + battery system,
and a Loxone Miniserver that today decides when the house needs heat and writes the geoTHERM's
heating mode directly.

Goal: use midday PV surplus to over-charge the underfloor slab so the house coasts through evening
and night without drawing grid or house battery.

The slab is the only thermal store in the system — `uih/EhpHeatBufferAvailable` reads `off` and both
buffer sensors read `cutoff` (no tank fitted). That is why `ehp/HcReturnTemp` reads directly on slab
charge state, and why a "thermal battery" strategy is viable at all.

### Division of responsibility

Each system does only what it uniquely knows:

| System | Owns |
|---|---|
| Loxone | Human comfort. Publishes one boolean: *is the house warm enough?* Stops writing the heat pump. |
| Home Assistant | Energy. Computes PV surplus, decides slab mode, writes two registers. |
| Vaillant | The machine. Weather compensation, VR 90 room influence, compressor protection, outdoor cutoff. |

HA writes only `mc/OperatingMode` and `mc/TempDesired`, and only ever `low` or `on` — **never
`off`**. That single rule makes the worst failure state "slightly cool", never "no heat".

### Control law

| Heating season | Slab mode | Loxone says | `mc/OperatingMode` | `mc/TempDesired` |
|---|---|---|---|---|
| off | — | — | `low` | `TDL` |
| on | no | warm enough | `low` | `TDL + 1` |
| on | no | heat needed | `on` | `TDL + 1` |
| on | yes | *ignored* | `on` | `TDL + 1 + offset` |

`TDL` = `mc/TempDesiredLow`, the only human knob. Heating season =
`sensor.heating_cooling_indicator` in (`active_heating`, `neutral`).

### Why the setpoint is derived, not captured

`TempDesired` is computed from `TempDesiredLow` every time, so there is nothing to save and restore
across a boost or an HA restart. Always compute the **absolute** target — never apply a relative
`current + offset`, which is not idempotent and would compound to `+2×offset` on a retry or a
restart mid-boost.

### Why grid export is not the surplus signal

The Victron battery absorbs surplus first, so `sensor.victron_grid_power_export` only goes positive
once the battery is full — too late in the day to charge a slab. And naive "generation minus load"
self-cancels: once the boost draws 2 kW, measured surplus drops by 2 kW and the boost cancels
itself. The surplus sensor therefore excludes the heating circuit's own draw, making it invariant
under our own action.

### Rejected alternatives

- **HA rebuilds room comfort from HA room sensors.** Loxone already holds per-room setpoints and
  weighting. Duplicating it would drift. Comfort during a boost is instead bounded by the offset
  cap, enforced by the Vaillant's own VR 90 room influence — so HA needs no room sensors at all.
- **HA toggles the VR 90's "Raumaufschaltung" (off/thermostat) room-influence setting.** This
  toggle is confirmed to exist and be ebus-communicated, but its own write is not in the public
  register catalog (only the continuous `mc/RoomTempOffset` "Raumaufschaltung" correction value
  is — see `packages/CLAUDE.md`). Since this design already doesn't use or need room-sensor trim
  (bedrooms are permanently throttled; Loxone's boolean is the sole comfort input), the setting is
  redundant with this architecture regardless of boost state — so the fix is a one-time manual
  change (below), not a register HA has to find and drive.
- **HA writes `off` to stop heating.** Removing `off` from HA's vocabulary is what makes every
  failure path safe.
- **`--mqttjson`.** The Loxone integration consumes these topics in the plain `;`-separated form
  and would break.

## Changes

### 1. `packages/heating_pv_boost.yaml` — new

Phase 1 (this step) is the **read-only decision layer**: ebusd telemetry, PV surplus, interlocks,
and `binary_sensor.heating_slab_mode_wanted` computing the full decision without acting on it.

### 2. `tests/conftest.py`

Seed every new MQTT-sourced entity in `baseline_states`; `test_templates.py` renders every `state:`
template strictly and fails on a sentinel output.

### 3. `packages/CLAUDE.md`

Verified register findings that outlive this plan (see that file).

## Transport — getting `ebusd/#` to HA's broker

This feature depends entirely on `ebusd/#` reaching the MQTT broker HA is configured against.
ebusd and its currently-connected broker are external infrastructure not tracked in this repo
(confirmed: no ebusd config, docker-compose, or `mosquitto.conf` exists anywhere in this git
tree). Two ways to close that gap, without moving ebusd itself:

### Option A — repoint ebusd directly at HA's broker

Change ebusd's own MQTT target (the `--mqtthost` / `--mqttport` / `--mqttuser` / `--mqttpass`
startup flags, or the equivalent docker-compose environment variables / systemd unit args on
whatever host runs ebusd) to point at HA's Mosquitto broker instead of its current one, then
restart the ebusd process/container.

1. On the ebusd host, find how ebusd is started (systemd unit, docker run/compose, or plain
   binary) and locate its current `--mqtthost=<value>` (or `MQTTHOST=` env var / compose
   `command:`).
2. Change that target to HA's broker's address/port (and credentials, if required) — the same
   host HA's own MQTT integration connects to (see HA's MQTT integration config entry for the
   exact value).
3. Leave every other ebusd MQTT flag untouched — in particular, do **not** add `--mqttjson`
   (Loxone consumes the plain `;`-separated payload format and would break).
4. Restart ebusd. Confirm with `mosquitto_sub -h <ha-broker> -t 'ebusd/#' -v` (or HA's MQTT
   integration's "Listen to a topic" panel) that messages arrive.

**Risk — why this is not the recommended option:** Loxone already ingests ebusd MQTT for
display, meaning it's subscribed to ebusd's *current* broker today. Repointing ebusd's publish
target moves that data out from under Loxone — its display would go stale/break unless Loxone is
also repointed at the same time, an extra, coupled change this plan does not otherwise need.

### Option B — bridge HA's broker to ebusd's existing broker (recommended)

Leave ebusd exactly as configured today (still publishing to its current broker, so Loxone's
integration is completely undisturbed) and instead configure HA's own Mosquitto broker to pull
`ebusd/#` in from ebusd's broker via a standard Mosquitto bridge. This mirrors the pattern already
live in this exact environment for the Heizung Shelly Pro 3EM (`packages/energy.yaml`, "bridged
from separate mosquitto broker under `shelly/` prefix") — HA's broker already runs at least one
working bridge; this adds a second, independent one.

1. On the host running HA's Mosquitto broker, add a bridge config — either appended to
   `mosquitto.conf` directly, or (cleaner, matching how the Shelly bridge is presumably already
   organized) a dedicated file under Mosquitto's `conf.d`/`include_dir`, e.g.
   `/etc/mosquitto/conf.d/ebusd-bridge.conf`:

   ```
   # Bridge: pull ebusd's topic tree in from its own broker, so HA can subscribe locally without
   # touching ebusd's own MQTT configuration or Loxone's existing integration.
   connection ebusd-bridge
   address <ebusd-broker-host>:<ebusd-broker-port>
   topic ebusd/# in 0

   clientid ebusd-bridge-to-ha
   try_private true
   start_type automatic
   restart_timeout 10 30

   # Only if ebusd's broker requires auth/TLS:
   # remote_username <user>
   # remote_password <pass>
   # bridge_cafile /path/to/ca.crt
   ```

   `topic ebusd/# in 0` is one-directional (ebusd's broker → HA's broker only) at QoS 0, matching
   ebusd's own default publish QoS.
2. Restart (not just reload/SIGHUP — that typically does not load new `connection` blocks)
   Mosquitto on HA's broker host.
3. Verify the bridge connected — check the Mosquitto log for a `Connecting bridge ebusd-bridge` /
   `... ready` line, or run `mosquitto_sub -h <ha-broker> -t 'ebusd/#' -v` locally on the HA
   broker host.
4. Nothing else changes — ebusd keeps publishing exactly as it does today, Loxone's existing
   subscription is untouched, and HA now sees the same `ebusd/#` tree locally.

**Recommendation: Option B.** It's purely additive — changes nothing ebusd or Loxone currently
depend on — versus Option A, which trades a known-working integration (Loxone's display) for a
simpler setup. Worth revisiting only if Loxone is ever retired or repointed separately.

## Post-deploy steps on the HA host (manual — user deploys via `git pull`)

1. Confirm `ebusd/#` reaches HA's broker at all — see "Transport" above; this gates everything
   else here.
2. Confirm `ebusd/ehp/HcReturnTemp`, `ebusd/mc/TempDesiredLow`, `ebusd/ehp/Backup`,
   `ebusd/uih/CoolingActive`, and the other five polled registers (`hwc/Status`,
   `mc/CoolingRequestHc2`, `uih/CoolingDemand`, `mc/TempDesired`, `mc/OperatingMode`) are
   published. `automation.heating_ebusd_poll_registration` (in `packages/heating_pv_boost.yaml`)
   now requests ongoing polling for all of these automatically on HA start and whenever ebusd
   comes back or finishes a bus scan — a manual `?N` publish should no longer be needed. If a
   topic still never appears after the automation has run at least once (check its trace, since
   its condition can block a triggered run while `sensor.heating_ebusd_scan_status` reads
   `"running"`), fall back to a manual check: `mosquitto_pub -h <broker> -t
   ebusd/<circuit>/<name>/get -m '?5'` (or `ebusctl -p 5 read -c <circuit> <name>`). If a topic
   never appears at all, the sensor stays `unavailable` — that is the signal; the documented
   fallback for `TempDesiredLow` specifically is `mc/Params` field 1.
3. Leave `--mqttjson` **off**.
4. Set VR 90 **Raumaufschaltung to "off"** (currently unconfirmed which value is live). This
   design does not use room-sensor trim — see `packages/CLAUDE.md` — so leaving it on "thermostat"
   only risks the VR 90 quietly undercutting a boost's `TempDesired` increase via
   `mc/RoomTempOffset`, never anything worse. Optional to confirm first with a live watch of
   `ebusd/mc/RoomTempOffset` while toggling the setting, if the mechanism is worth nailing down
   exactly rather than just switched off.

## Status

- [x] 1. In-repo plan file
- [x] 2. `packages/heating_pv_boost.yaml` — Phase 1 read-only decision layer
- [x] 3. `tests/conftest.py` seeds for the new MQTT entities
- [x] 4. `packages/CLAUDE.md` — register findings
- [x] 5. `README.md` — package section
- [x] 6. `tests/test_heating_pv_boost.py` — surplus, derived setpoint, DHW mask, interlocks
- [x] 7. `packages/heating_pv_boost.yaml` — `heating_ebusd_poll_registration` automation: scheduled
      ebusd poll-priority registration, gated on `sensor.heating_ebusd_scan_status` not reading
      `"running"` — closes the "may not auto-publish" gap on 9 of the 10 registers this feature
      reads; see the "Transport" section for Option A (repoint) vs Option B (bridge, recommended)
      for the still-open question of whether `ebusd/#` reaches HA's broker at all
- [ ] 8. Observe for several days; calibrate the return-temp saturation threshold, validate the
      polling priority tiers against real cadence, and confirm whether ebusd's steady scan-status
      value is `"finished"` or `"OK"`
- [ ] 9. Loxone: publish `warm_enough`; stop writing the geoTHERM heating mode
- [ ] 10. Vaillant: set a real `mc/TempDesiredLow` below the intended day temperature
- [ ] 11. Phase 2 — comfort control (`low`/`on` + derived setpoint)
- [ ] 12. Phase 3 — slab boost
- [ ] 13. Phase 4 — tests, dashboard

### Checks run locally

- `yamllint -c .yamllint.yaml packages/heating_pv_boost.yaml` — clean, no warnings
- `.github/scripts/fix_yaml_style.py .` — "All files already clean", no diff
- `.github/scripts/resolve_ha_yaml.py configuration.yaml .` → `yamllint` — clean (3241 lines)
- `.github/scripts/extract_templates.py` — 12 strict `state:` templates, 17 runtime, all extracted
- **`homeassistant --script check_config` against the pinned image (2026.9.1) — PASSES**, with
  `secrets.yaml` from `fakesecrets.yaml`, the injected Linz coordinates, the `climate_template`
  custom component and the workday fixture, exactly as CI does it
- `--script check_config --info all` confirms all 18 new entities are loaded, so the package is
  genuinely parsed rather than silently skipped
- `python3 -m ast` parse of `tests/conftest.py` and `tests/test_heating_pv_boost.py`

### Not runnable in this environment

- `pytest tests/` (needs a live HA container via `ha_integration_test_harness`), so
  `tests/test_heating_pv_boost.py` is written against the documented harness API and the existing
  test patterns but has not been executed — CI is its first run
- Anything touching the real MQTT broker or the ebus, so every topic name and payload shape is
  taken from the captured dump rather than observed live
