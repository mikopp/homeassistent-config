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
| Loxone | Human comfort. Publishes one boolean: *is the house warm enough?* No longer writes the heat pump (done 2026-10-30). Does **not** control room valves. All loops and valves are open, no bedroom throttling (owner, 2026-11-06). |
| Home Assistant | Energy. Computes PV surplus, decides slab mode, writes two registers. |
| Vaillant | The machine. Weather compensation, VR 90 room influence, compressor protection, outdoor cutoff. |

HA writes only `mc/OperatingMode` and `mc/TempDesired`. The mode is only ever `on` or `off` —
never `auto` or `low` (owner, 2026-11-14).

**Why the 10-30 law was replaced (2026-11-14).** The 10-30 law (`auto` normally, `on` for "not
warm enough") let Loxone only *add* heat. Once Loxone stopped writing `low` on 10-30, nothing
turned the heating down and the house overheated. Loxone's `warm_enough` must be able to stop the
geoTHERM.

**Decided (owner, 2026-11-14):**
- **Heat = `on`, never `auto`.** `on` and `auto` differ only in the geoTHERM's day/night time
  program; the time program is ignored. Loxone owns the schedule through `warm_enough`. With `on`
  the setpoint is always `TempDesired` (= `TDL + 1`), so `TempDesiredLow` no longer acts as a night
  setback, only as the base the setpoint is derived from.
- **Warm enough = `off`** in `active_heating` and `neutral`, unless a slab boost overrides it
  (boost only in `active_heating`).
- **Not warm enough = `on`.** Loxone silent for 24 h (`binary_sensor.heating_loxone_online` off)
  counts as not warm enough, as do `unknown`/`unavailable`: a lost signal heats, never stops.
- **At most one mode change every 30 min** (compressor minimum between starts is 20 min). A change
  that falls inside the hold is applied when the hold ends, not dropped.
- **Cooling season → heating `off`** (unchanged from 10-30). `mc/OperatingMode` is the *heating*
  mode only ("Betriebsmodus Heizen", enum `0=disabled 1=on 2=off 3=auto 4=eco 5=low`, no cooling
  value); cooling is the separate register `mc/CoolingOperatingModeHc2`, so `off` does not touch
  cooling. The indicator works on a 48 h outdoor mean with hysteresis, so a single warm day cannot
  change the season.
- An `unknown`/`unavailable` **season indicator** writes nothing (mode stays as it is).

Safety trade-off (accepted by the owner): `off` is now a normal heating-season state, so a stuck
"warm enough" could leave the house unheated. Mitigations: 24 h silence → heat; garbage/empty
Loxone payload already renders "not warm enough"; Loxone's own comfort logic decides, not HA.

### Control law

First matching row wins (owner, 2026-11-14):

| # | Indicator | Slab mode wanted | Loxone `warm_enough` | `mc/OperatingMode` | `mc/TempDesired` |
|---|---|---|---|---|---|
| 1 | `unknown` / `unavailable` | — | — | unchanged | unchanged |
| 2 | `passive_cooling` / `active_cooling` | — (never) | — | **`off`** | `TDL` |
| 3 | `active_heating` | **on** | any (overridden) | **`on`** | `TDL + 1 + offset` |
| 4 | `active_heating` | off / `unknown` | on | **`off`** | `TDL + 1` |
| 5 | `active_heating` | off / `unknown` | off / `unknown` / `unavailable` / silent 24 h | **`on`** | `TDL + 1` |
| 6 | `neutral` | — (never) | on | **`off`** | `TDL + 1` |
| 7 | `neutral` | — (never) | off / `unknown` / `unavailable` / silent 24 h | **`on`** | `TDL + 1` |

`TDL` = `mc/TempDesiredLow`, the only human knob. **Slab boosting happens only in
`active_heating`** (owner, 2026-10-30) — implemented in `binary_sensor.heating_slab_mode_wanted`;
`unknown` (20 min after every restart) counts as off. `binary_sensor.heating_season_active`
(`active_heating` or `neutral`) gates rows 3–7.

- Edges: a boost ending while Loxone says warm enough → row 4, `off`; a boost starting while the
  mode is `off` → row 3, `on`.
- Every mode change respects the 30 min hold. A `TempDesired`-only change (row 3 ↔ row 5, mode stays
  `on`) does not start or stop the compressor and is not held.
- Rows 4 and 6 still write `TDL + 1` so nothing has to be saved or restored across a mode change.
- The order matches `sensor.heating_control_state` (cooling → off-season → slab → … → warm enough →
  heating).

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
  is — see `doc/heating_pv_boost/notes.md` "Room influence"). Since this design already doesn't use or need room-sensor trim
  (Loxone's boolean is the sole comfort input; bedrooms are not throttled, all valves open — owner 2026-11-06), the setting is
  redundant with this architecture regardless of boost state — so the fix is a one-time manual
  change (below), not a register HA has to find and drive.
- **HA never writes `off` in heating season** (10-30 law). Rejected 2026-11-14: without `off`
  (or `low`) Loxone cannot stop the heating and the house overheats. Replaced by the mitigations in
  "Decided (owner, 2026-11-14)".
- **`auto` with the geoTHERM time program** (10-30 law). Rejected 2026-11-14: Loxone owns the
  schedule; `on`/`off` only.
- **`--mqttjson`.** The Loxone integration consumes these topics in the plain `;`-separated form
  and would break.

## Changes

### 1. `packages/heating_pv_boost.yaml` — new

Phase 1 (this step) is the **read-only decision layer**: ebusd telemetry, PV surplus, interlocks,
and `binary_sensor.heating_slab_mode_wanted` computing the full decision without acting on it.

### 2. `tests/conftest.py`

Seed every new MQTT-sourced entity in `baseline_states`; `test_templates.py` renders every `state:`
template strictly and fails on a sentinel output.

### 3. `doc/heating_pv_boost/notes.md`

Verified register findings that outlive this plan (see that note and
`doc/heating_pv_boost/registers.md`).

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

### Option B — bridge HA's broker to ebusd's existing broker (recommended — DEPLOYED)

> **As deployed (owner, 2026-10-30): the bridge is an explicit per-topic allowlist, not the
> `topic ebusd/# in 0` snippet below** — which never was what got deployed, and could not have
> worked on its own: it carries nothing outbound, so HA's `/get` poll registrations would never
> reach ebusd. Live: one `topic ebusd/<circuit>/<name> in 0` line per state topic HA reads, one
> `topic ebusd/<circuit>/<name>/get out 0` line per poll registration, `ebusd/global/running` and
> `ebusd/global/scan` `in` only. Every new register needs both lines — see
> `doc/heating_pv_boost/notes.md` "Invariants". Writes need a third kind of line:
> `topic ebusd/<circuit>/<name>/set out 0` (Phase 2: `mc/OperatingMode` and `mc/TempDesired`, see
> `plans/heating-baseline-and-phase2-prerequisites.md` step 2). The snippet below is kept for the
> history only.

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
   its condition can block a triggered run while `sensor.ebusd_heating_ebusd_scan_status` reads
   `"running"`), fall back to a manual check: `mosquitto_pub -h <broker> -t
   ebusd/<circuit>/<name>/get -m '?5'` (or `ebusctl -p 5 read -c <circuit> <name>`). If a topic
   never appears at all, the sensor stays `unavailable` — that is the signal; the documented
   fallback for `TempDesiredLow` specifically is `mc/Params` field 1.
3. Leave `--mqttjson` **off**.
4. Set VR 90 **Raumaufschaltung to "off"** (currently unconfirmed which value is live). This
   design does not use room-sensor trim — see `doc/heating_pv_boost/notes.md` "Room influence" — so leaving it on "thermostat"
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
      ebusd poll-priority registration, gated on `sensor.ebusd_heating_ebusd_scan_status` not reading
      `"running"` — closes the "may not auto-publish" gap on 9 of the 10 registers this feature
      reads; see the "Transport" section for Option A (repoint) vs Option B (bridge, recommended)
      for the still-open question of whether `ebusd/#` reaches HA's broker at all
- [x] 7a. `sensor.heating_pv_surplus` fix: clamp at 0 (was `-house_load` with no sun); missing PV
      sources count as 0 W; unavailable only when Victron load or the heating clamp is unavailable.
      Tests added in `tests/test_heating_pv_boost.py`. Deployed; clamp confirmed live 2026-10-17
      (reads 0 with no PV). Residual night-time transient spikes: see Observations, finding 2.
- [x] 7b. Indicator thresholds as `input_number` settings (+ `*_effective` clamp sensors) and
      `automation.pergola_sync_heating_from_indicator` (PR #123). CI fixes: the sync automation
      names both seasons explicitly (no `default:` that turned the boolean off when run with the
      indicator unavailable); season tests drive the 48h mean and assert the indicator instead of
      pinning it with `set_state()` (it re-renders itself via `this`). Deployed; the indicator reads
      `active_heating` live and `binary_sensor.heating_season_active` follows it.
- [x] 7c. Transport + poll registration confirmed live (2026-10-17): `ebusd/#` reaches HA's broker,
      all registers this feature reads publish, and `heating_ebusd_poll_registration` fires on each
      HA restart (scan → `finished`) and repopulates the `mc/*`/cooling sensors within ~1–2 s.
      ebusd's steady scan-status value is `"finished"` (never saw `"OK"`).
- [ ] 8. Observe for several days; calibrate the return-temp saturation threshold and validate the
      polling priority tiers against real cadence. PARTLY DONE: scan-status value settled
      (`"finished"`). BLOCKED on `input_boolean.heating_pv_boost_enabled` being off, so
      `slab_mode_wanted` has produced no decision data yet. Return-temp calibration also needs a real
      boost (return only reached ~24 °C in ordinary heating cycles; the 28 °C threshold is untested).
      Tier cadence only partly measurable: `HcReturnTemp` updates every 30–85 s; unchanged registers
      (`TempDesiredLow` etc.) are not re-reported, so their poll rate cannot be read from HA.
- [x] 8a. Fix `sensor.heating_pv_surplus` night-time transient spikes (see Observations, finding 2):
      result capped at real PV generation (`solar_yield_watts` + `victron_ac_inverter_power`) so
      "no PV ⇒ no surplus" holds regardless of the Shelly-vs-Victron update skew. Tests added.
      Awaiting deploy; verify no night-time surplus > 0 afterwards.
- [x] 8b. Phase 2 prerequisite: `binary_sensor.heating_compressor_active` (Shelly clamp > 500 W) —
      owner chose the Shelly as the source, so no new ebus register or MQTT topic. Tests added.
      REMOVED 2026-11-14 (owner: nothing read it, `ehp/Comp` is the compressor; Phase 2 re-adds an
      electrical threshold if it needs one). `Hc1Pump` still unread (open question in
      Observations, finding 4).
- [ ] 8c. Set `input_number.heating_pv_min_battery_soc` to 50 (UI, user). The current 30 equals the
      Victron's own floor, so the gate never blocked.
- [x] 9. Loxone: publish `warm_enough`; stop writing the geoTHERM heating mode — owner, 2026-10-30.
      Loxone still publishes `warm_enough`, no longer writes the mode, and never controlled room
      valves. The geoTHERM now runs `auto` on its own time program; HA will switch to `on` only
      for "not warm enough" or a boost (decided 2026-10-30; superseded 2026-11-14 by the
      `on`/`off` law, see "Control law").
- [x] 10. Vaillant: set a real `mc/TempDesiredLow` below the intended day temperature
      (live 2026-10-30: TDL 21, TempDesired 22)
- [x] 11. Phase 2 — comfort control IMPLEMENTED (not yet deployed): `sensor.heating_wanted_operating_mode`,
      `sensor.heating_target_temp` (boost only in `active_heating`), `automation.heating_comfort_control`
      (writes only on a read-back difference, 30 min mode hold via
      `input_datetime.heating_mode_last_written`, no write with the master switch off / ebusd offline /
      unknown season), tests in `tests/ha/test_heating_pv_boost_comfort.py`. Control law revised by
      the owner 2026-11-14, see "Control law". Post-deploy steps (owner, in this order):
      1. Add `topic ebusd/mc/OperatingMode/set out 0` and `topic ebusd/mc/TempDesired/set out 0` to the
         Mosquitto bridge (`plans/heating-baseline-and-phase2-prerequisites.md` step 2), restart Mosquitto.
      2. Prove each line with an idempotent write of the CURRENT value (e.g. publish the current
         mode name / setpoint, `22.0` form for TempDesired: the one-decimal payload is unverified)
         and see ebusd accept it.
      3. Arm `input_boolean.heating_comfort_control_enabled` (no `initial:`; off until then).
      Open: the setpoint payload form against live ebusd; whether ebusd echoes a written value on
      the read topic (the writer waits for the read-back, polls refresh it otherwise).
- [ ] 12. Phase 3 — slab boost
- [ ] 13. Phase 4 — tests, dashboard
- [ ] 14. Compressor short-cycling observation + tuning — separate plan,
      `plans/heating-compressor-cycling.md`

## Observations (2026-10-17, ~46 h of live data, boost disabled)

Source: ha-mcp read-only queries (history, statistics, traces). Graded: CONFIRMED = read directly from
recorded data; OBSERVED = real data with an alternative explanation still open.

1. **Read path works (CONFIRMED).** All entities live, no ebusd/heating log errors. The DHW mask
   `delay_off` ends exactly 25:00 after the generator leaves `water` (17:25:37 → 17:50:37).
   `warm_enough` is the exact inverse of `mc/OperatingMode` (`on` ⇔ `warm_enough` off), lagging ~1.8 s,
   i.e. Loxone still writes the mode (step 9 pending) and publishes the boolean right after.
2. **Surplus transient spikes at night (CONFIRMED).** 2026-10-17 00:17:44: Shelly heater power jumped
   155 → 1563 W at :44.689 while `victron_pv_net_power` was still −331 W and only reached −2220 W
   by :48 (Victron load ramps over ~4 s, per-phase updates). `heating_pv_surplus` = net + heater
   therefore read 1232 W with no sun, falling to 0 by :46.6. `victron_pv_net_power` itself is
   correct (never positive); the artefact is purely the sum of two sources with different latency.
   Harmless to `slab_mode_wanted` (15 min `delay_on`) but wrong for any undebounced consumer.
   Fix direction: `min(net + heater, PV generation)`.
3. **SOC gate was a no-op (CONFIRMED).** Battery sat at exactly 30 % from ~04:00 to 09:00 on 10-17
   (the Victron floor) and the gate is `soc < 30`. Owner sets the helper to 50.
4. **Machine activity vs `hvac_action` (owner-supplied Loxone logic).** Loxone derives its status from
   `ehp/Status` hcmode plus two more registers: `heat` + `ehp/ActualEnvironmentPower` > 1 → heating
   active; `heat` + power 0 → heating passive; `water` → hot water; `off` + `ehp/Hc1Pump` = 1 →
   circulation pump; `off` + pump 0 → off. A Loxone `on` mode is a permission, not a command; the
   compressor runs on the machine's own schedule and the pump circulates between runs. HA currently
   sees only hcmode, so `heat`/`off` cannot tell compressor from circulation. Open: recorded Shelly
   power shows ~83 W in `heat` (idle) and ~9 W in `off`, which does not obviously match "pump runs
   while `off`" — needs `Hc1Pump` read live to reconcile.
5. **Heating draw (owner-confirmed).** Heating never exceeds ~2 kW, usually ~1.8 kW, so the 2000 W
   start threshold is right. (Hourly maxima of 2.0–2.6 kW in statistics were start-up peaks; DHW
   ~3.5 kW.) 10-16 never reached 2 kW for 15 min; 10-17 morning would have started ~09:15.
6. **Restart behaviour (CONFIRMED).** `slab_mode_wanted` goes unavailable → unknown, then `off` after
   the 20 min `delay_off` (20:48 restart → `off` 21:11). Phase 3 must treat `unknown` as off.
7. **Possible outdoor shutdown (OBSERVED, one day).** 10-17 `hvac_action` `off` 13:52–17:00 matched
   outdoor ≥ 15 °C (`mc/OtShutdownLimit`); 10-16 14:43–16:11 `off` at ~13 °C is unexplained. Whether
   a boost is honoured above 15 °C is untested — check on the first armed sunny day.

8. **Owner changes and short-cycling (2026-10-30, owner-reported).** Loxone stopped writing the
   mode; geoTHERM set to `auto` with a day `on` / night `low` time program; `CompIntegral`
   −150 → −180 °min; heating curve 0.15. In mild weather the compressor still starts about once an
   hour and runs about 5 min. Analysis and observation sensors: `plans/heating-compressor-cycling.md`.

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

## Close
- [TODO] Close: distil into note/design/skill, story → background, update pointers, delete this plan (`doc/KNOWLEDGE.md#K-6`)
