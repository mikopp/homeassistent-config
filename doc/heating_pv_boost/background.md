Background only: not design-relevant; current facts are in doc/heating_pv_boost/notes.md.

# heating_pv_boost: background

History, investigations and one-day snapshots for `packages/heating_pv_boost.yaml`. Never cite this
file as current behaviour; current package facts are in `doc/heating_pv_boost/notes.md`,
register decodes in `doc/heating_pv_boost/registers.md`. IDs `HPB-B<n>` are stable.
Text below is kept as written at the time (moved out of the note and the YAML comments).

## HPB-B1 Live confirmations (dated provenance)

- **2026-09-18, live `ebusctl` test.** `ehp/HcReturnTemp` answered a forced read cleanly
  (temp=23.56 sensor=ok), so the register and the hardware behind it both work end to end.
  `mc/TempDesiredLow` answered a forced read with 21.0 °C. Both were then NOT yet confirmed to
  publish on MQTT unprompted (via ebusd's own background poll); the fix if they stayed
  unavailable was publishing `?5` to `ebusd/<circuit>/<name>/get`. `TempDesiredLow` was called
  "the single most important register to see arrive live", fallback `mc/Params` field 1.
  Superseded by the poll-registration automation (HPB-B3).
- **2026-10-17.** `ebusd/#` reached HA's broker at the time, `ehp/HcReturnTemp` published every
  30–85 s, and the registration automation repopulated the `mc/*` sensors within ~1–2 s of each
  HA restart (see the plan's Observations). Later (2026-10-30) the owner supplied the live
  bridge config: it is an explicit per-topic allowlist, not `ebusd/#`.
- **2026-10-30, owner `ebusctl` forced reads of the compressor tuning registers.** Values that
  day: `CompHysteresis` `7.00`, `CompIntegral` `-180`, `Integral` `5`, `CompDemand` `no`,
  `CompStartsHc` `13385`, `CompHoursHc` `13277`, `YieldTotal` `127550`, `BackupIntegral` `-600`,
  `mc/Status0a` `23.94;off;on;off;24` (flow 23.94 °C, setpoint 24 °C).

## HPB-B2 Config generations and naming (from YAML comments)

- `ehp/Status` field 3: an OLDER ebusd config generation (the frozen `archived/` tree) names it
  `hcmode2`, with an enum lacking `1=cooling`, so cooling would arrive as raw `1` there. Absent
  from the currently-served config; which generation this ebusd instance runs was never
  confirmed, so both enum forms stayed accepted.
- `sensor.geotherm_heating_circuit_flow_temp` naming essay: the entity is named "circuit" rather
  than a bare "flow temp" because `ehp/FlowTemp` (VF2, system-wide flow sensor) also exists and
  answers a different question. The register's "Hc" abbreviation was not reused in the entity id
  because HA derives the entity_id from the friendly `name:` via slugify, not from `unique_id:`
  (confirmed against a real boot's entity registry at the time), so name and id had to match after
  slugifying; spelling "circuit" out in both kept that guaranteed.

## HPB-B3 ehp/Status self-publishing assumption

`ehp/Status` was originally assumed to be the exception that self-publishes every few seconds,
so it was not registered for polling. That held only while the compressor was actively running;
idle/passive circulation let it go quiet far past the liveness window. It is now registered at
priority 3 like every other register.

## HPB-B4 Raumaufschaltung investigation

**CORRECTION (superseding an earlier note):** a "Raumaufschaltung: off/thermostat" toggle does
exist on this installation and is ebus-communicated, confirmed directly by the owner, who switches
it from both the VR 90 menu and the geoTHERM's own panel. An earlier version of the note claimed
room influence "has no mode selector" and is structurally additive-only; that claim was reasoned
from the register catalog alone.

**The toggle itself is not a separate cataloged register.** An exhaustive re-search of the live
GitHub Pages CSVs (`mc`, `ehp`, `uih`, `rcc`, `hwc`, `cc`, `broadcast`, refetched fresh, not the
stale local clone) for `aufschalt`, `thermostat`, `raum*`, and every `UCH`/enum field on all six
circuits found exactly one register whose comment literally says "Raumaufschaltung":
`mc/RoomTempOffset` (`b505 2d`, write-only, plain signed `D2C` °C value, no enum, no mode flag).
Two explanations fit the evidence (HYPOTHESES, never live-verified):

1. **Most likely**: "off"/"thermostat" is a VR 90-side (and mirrored geoTHERM-panel-side) menu
   selection that governs whether the VR 90 writes to `mc/RoomTempOffset` at all, not a separate
   discrete register: "off" means the VR 90 never sends a correction (or a fixed neutral one);
   "thermostat" means it actively trims the flow setpoint from its own room reading.
2. **Possible**: the toggle is a genuine installer-level parameter the community catalog never
   captured (the CSVs are reverse-engineered from typical runtime traffic; installer-menu-only
   parameters are what such catalogs miss).

The way to settle it: watch `ebusd/mc/RoomTempOffset` on MQTT (or
`ebusctl read -f -c mc RoomTempOffset`) while toggling Raumaufschaltung on the hardware, to see
whether the write starts/stops appearing or a different message ID shows up.

The original (pre-verification) reference plan's Task 3.1 reacted to the concern that in
"thermostat" mode the VR 90 could write a compensating correction through `RoomTempOffset` as the
room warms during a boost. Resolution folded into the plan: set Raumaufschaltung to off as a
one-time manual change; if room trim were ever wanted outside boosts only, HA would have to toggle
it itself, which needs its literal ebus write (not found; needs a live capture during a toggle).

## Comfort helper replaces `mc/TempDesiredLow` as the comfort knob (2026-11)

Phase 2 derived the written setpoint from `mc/TempDesiredLow` (TDL). The owner found frost protection
active on the geoTHERM: below 3 °C outdoor, mode `off` still heats towards TDL, and the compressor
does start (owner-verified). With TDL at 21 (= comfort) `off` was therefore ineffective. TDL became a
hand-set frost floor (20) with no HA logic, and `input_number.heating_comfort_temp` (18-24 °C, step
0.5, no `initial:`) became the only comfort knob; the TDL sensor was removed. Whether the controller
ignores the room temperature during the frost request (H1) was never verified: the owner accepted
frost heating either way, so the check was dropped.

## Compressor short-cycling: observation and tuning (2026-10-30 to 2026-11-21)

From the closed plan `heating-compressor-cycling`.

- **Start (2026-10-30).** In mild weather the geoTHERM started about once an hour and ran about
  5 min, close to `TimeCompOnMin` (240 s). The owner had raised `CompIntegral` −150 → −180 °min,
  curve 0.15, mode `auto` with the unit's day `on` / night `low` time program. Loxone mode
  toggling, room valves and throttled loops were ruled out by the owner (all loops and valves
  open). The plan added nine read-only registers (`ehp/Integral`, `ehp/CompDemand`, `mc/Status0a`
  flow setpoint, `CompIntegral`, `CompHysteresis`, `BackupIntegral`, `CompStartsHc`, `CompHoursHc`,
  `YieldTotal`), the derived run statistics, the "Compressor cycling" dashboard card and the
  "Why runs end" graph; later `sensor.heating_compressor_stop_temp`. `BackupModeHc` read
  `no_backup`, `BackupIntegral` −600 (owner, 2026-10-30).
- **Baseline week 2026-10-31…11-06:** 9–11 heating starts a day, 2–4 h, outdoor mean falling
  7.4 → 2.2 °C. Run anatomy on 11-06: night run at setpoint 26 °C stopped at 33 °C after ≈ 10 min
  with the return flat at 24.9 °C and flow = return + ≈ 8.3 K, integral only −180 → ≈ −125; a day
  run at setpoint 27 °C lasted ≈ 30 min (return creeping ≈ 0.04 K/min) and repaid the integral.
  This gave the headroom model now in the note (spread puts the flow at the stop point at once).
- **Pump speed (2026-11-06):** the catalog's pump-speed registers (`HcPumpStatus`, `HcPumpPWM`,
  `Hc1PumpSpeedControlDirectCircuit`…) need SW ≥ 407; `ebusctl info` showed `SW=0383`, so none
  exist. Left on the flow side: a physical selector on the pump (unverified) or a dirt filter
  check (installer).
- **Night setback test (planned 2026-11-06, superseded 2026-11-14):** `TempDesiredLow` 21 → 22 °C
  for 3 nights. Dropped when the mode law changed to `on`/`off` and TDL became the frost floor.
- **Buffer tank (assessed 2026-11-06, parked):** a parallel buffer adds ≈ +6 min per run per 100 l
  at a COP and cost penalty; a series buffer does not change the spread. Not pursued.
- **Hot water:** runs the same compressor (1–2 starts a day), freezes the heating integral and
  warms the slab afterwards. Since 2026-11-14 the run statistics follow `ehp/Comp` in every mode
  (plan `heating-cycling-from-ehp`); earlier baselines excluded (11-06…11-14) or Shelly-counted
  (before 11-06) hot-water runs, so they are not comparable with later ones.
- **Result (2026-11-21, ha-mcp, OBSERVED):** 2026-11-14…20 had 34 heating starts (≈ 4.9 a day)
  plus 2 hot-water starts a day, daily mean run 22–30 min, no run under 11 min since 11-15, runs of
  25–42 min on 11-20; hysteresis 7 K, start integral −180. Confounded with the curve changes
  0.15 → 0.13 (≈ 11-14) → 0.14 (11-20 evening, read-back confirmed), `TempDesired` 22.5 (HA) and
  the mode change to `on`. Integral and flow at run stop were not extracted.
- **Owner decision (2026-11-21):** no `CompHysteresis` +1 K for now; the plan was closed.
