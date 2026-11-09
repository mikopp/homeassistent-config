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
