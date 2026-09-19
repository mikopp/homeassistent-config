# Packages — Feature-specific Claude notes

Directory-scoped knowledge for individual feature packages. Keep the root `CLAUDE.md` general; put
package-specific hardware quirks and design rules here.

## airflow_cooling.yaml — ComfoConnect ventilation

### Boost/preset hardware model
Hardware behaviour of the ComfoConnect unit, relied on by the airflow automations:
- A running **boost** is identified by `switch.comfoconnect_pro_boost` (and the stable `drying_needed`
  intent) — **never** by `preset==high`. Boost only *reports* `high` as a side effect.
- Boost delivers HIGH airflow and **coexists with `auto_mode` ON**. On boost end the preset returns to
  its pre-boost value.
- **Two actions CANCEL a running boost:** (1) writing ANY preset (`low`/`medium`) via
  `select.select_option`, and (2) turning `auto_mode` **OFF** (airflow lingers high a few minutes, then
  reverts). Turning `auto_mode` **ON** does NOT cancel boost.
- `number.comfoconnect_pro_boost_time` is a live countdown; **writing it does NOT extend a running
  boost** in place (the device ignores it) — the value only reaches ~60 again via a switch off→on
  restart.

### Template sensor pattern — trigger-based vs state-based
A derived template `binary_sensor` whose inputs are **only other (slow) binary sensors** MUST be
**state-based** (plain `state:`, no `trigger:`). Trigger-based template sensors restore their last
state on HA **restart** and recompute only when an input **changes** — so a derived-from-binaries
sensor can restore **stale** and never resync (this is what stranded `ventilation_low_needed` at
`off` while `heat_low` was `on` all day, leaving the preset at medium under `heat_protection`).
Reserve trigger-based + restore for **primary** decision sensors driven by continuously-drifting
numeric filters (outdoor temp/dew, weather-station temp): there the drift guarantees a recompute
within ~1 debounce after restart, and restoring preserves the 10-min delay + `this.state` Schmitt
hysteresis. Note the `to: "unknown"` self-trigger covers *reload* (comes up `unknown`), **not**
*restart* (comes up with a restored value), so it does not protect against restart-stale.

### Ventilation controller (`automation.airflow_ventilation_controller`, Section 2) rules
- Gate preset/auto ownership on the **stable intent sensors** (`drying_needed` ⊇ `flush_needed`), NOT
  the boost/auto switches, which flap during boost expiry/re-enable races.
- While a boost is intended/running: write **no preset** and only ever turn `auto_mode` **ON** (or do
  nothing). The boost-owner branch is first in the `choose` and matches on the intent, so the `choose`
  EXITS there and the Low/Medium branches (which turn auto off / write a preset) can never cancel the
  boost. Boost gives HIGH meanwhile, so the underlying preset is moot until boost ends.
- Force `preset=medium, auto=off` only when `drying off`, `flush on`, and the schedule is holding
  `preset=low`; `auto=on, preset=medium` is the preferred state and must not be re-forced.
- Prefer minimal, surgical controller edits over restructures; retain existing branch behaviour unless
  a change is required to fix a specific defect.

## energy.yaml — Energy Dashboard metering

### Dashboard-facing entities are function-named wrappers, never vendor entities
Anything the Energy Dashboard references must be a **function-named** entity that this repo owns —
`sensor.wallbox_power`, `sensor.wallbox_energy` — defined as a thin `template:` wrapper over whatever
integration currently supplies the reading. Never point the dashboard at a vendor/integration entity
(`sensor.evcc_loadpoint_1_*`, `sensor.go_echarger_*`, …) directly.

Rationale: the Energy Dashboard config lives in `.storage/energy` (gitignored, UI-only) and stores
*entity ids*. Long-term statistics are keyed by entity id too. So a vendor entity id in the dashboard
means every source swap costs a manual entity rename to keep history, plus a dashboard edit. With the
wrapper, a swap is a one-line change to `state:`/`availability:` and nothing downstream moves.

Corollaries:
- **Normalise units in the wrapper** from the source's own `unit_of_measurement`
  (`state_attr(src, 'unit_of_measurement')`), rather than hard-assuming the source's scale. Vendor
  firmware picks its own units and a replacement source will differ.
- **Declare `device_class` / `state_class` on the wrapper.** Some discovery payloads omit
  `state_class` (go-e's `total_energy_charged` does), which alone makes an entity unselectable in the
  Energy Dashboard. The wrapper is where that is fixed.
- **Lifetime counters use `state_class: total_increasing`**, so HA absorbs a counter reset and
  baselines on the first observed value instead of booking the pre-existing total as consumption.
- **Never merge two sources into one statistic id.** Two chargers' lifetime counters have different
  absolute baselines; if the new one reads higher, `total_increasing` books the difference as real
  consumption — a phantom spike of potentially thousands of kWh. Start a new series instead.
- Wrappers propagate `unavailable` rather than substituting `0`. A gap in the dashboard is honest;
  a fabricated 0 on a counter is not. (`packages/pergola.yaml`'s PV wrapper maps stale→0 only because
  a downstream rule requires `pv == 0` at night.)
- New source entities need a seed in `tests/conftest.py::baseline_states` — `test_templates.py`
  renders every `state:` template strictly and fails on a sentinel output.

## heating_pv_boost.yaml — Vaillant geoTHERM via ebusd

Verified against a full `ebusctl` dump of the live bus and the **published** ebusd Vaillant
message definitions at `https://ebus.github.io/de/vaillant/*.csv` — this is the config ebusd
≥24.1 actually downloads and runs. **Do not use the `archived/` CSVs in a local
`john30/ebusd-configuration` checkout as a source** — that tree is a frozen historical
snapshot and does not reflect the currently-served definitions (confirmed divergences below).
These findings outlive any one plan — check here before adding an ebusd register, and
re-verify against the live URL above rather than any local clone.

### Bus participants

| Addr | Device | Circuits |
|---|---|---|
| 08 / 23 / 25 / 50 | geoTHERM `EHP00`, art. `0010002787` | `ehp`, `cc`, `hwc`, `mc` |
| 15 | control interface `UIH00` | `uih` |
| 75 | VR 90/3 remote control, art. `0020040079` | `rcc` |
| 05 | VR 920 internet module, art. `0020252922` | none — **dormant**, Vaillant discontinued the service |

There is **no VRC 700 and no `700` circuit**, so `Hc1RoomCircuitMode`, `Z1DayTemp` and friends do
not exist here. The VR 90 writes to the bus but accepts and keeps a value HA writes, so HA is the
sole effective writer of the control registers.

### Payload format — do NOT enable `--mqttjson`

ebusd publishes plain `;`-separated values, and **the Loxone integration consumes these same topics
in that format**. Switching to JSON would break it. Multi-field messages are therefore parsed
positionally; document the field list inline at every such sensor.

### Poll-priority registration is a runtime MQTT action, not just a CSV `poll` column

Publishing `?N` (N = priority digit 1-9) to a register's `ebusd/<circuit>/<name>/get` topic does
two things at once: performs an immediate read AND enables ONGOING automatic polling of that
register at priority N going forward. An EMPTY payload to the same topic is different — it's a
ONE-TIME forced read only, no ongoing polling. `automation.heating_ebusd_poll_registration` in
`packages/heating_pv_boost.yaml` uses the `?N` form for exactly this reason.

**Confirmed by the system owner: a runtime-set poll priority does NOT survive an ebusd process
restart.** ebusd also publishes its own process status to MQTT under `ebusd/global/*` (retained
topics): `running` (`"true"`/`"false"`, set to `"false"` as an MQTT last-will when ebusd
disconnects); `scan` (`"OK"` / `"running"` / `"finished"` — its bus/device discovery status);
`version`; `uptime`; `signal`. `binary_sensor.heating_ebusd_running` and
`sensor.heating_ebusd_scan_status` (in `packages/heating_pv_boost.yaml`) expose the first two.

**Sequencing rule (owner-confirmed): a poll priority must not be registered while `scan` reads
`"running"`** — ebusd may still be mid-discovery of what's on the bus, so the message catalog a
registration targets can be incomplete. Register only once `scan` leaves `"running"`, and
re-register whenever it transitions back to `"running"` and out again (a fresh scan — most likely
correlated with an ebusd restart, but treated as its own signal regardless of cause).
`heating_ebusd_poll_registration` gates on this with a single condition
(`{{ states('sensor.heating_ebusd_scan_status') != 'running' }}`) applied uniformly across all of
its triggers, rather than allowlisting one specific resting value — it's undocumented whether
ebusd's steady state after a scan is `"finished"` or settles back to `"OK"`, and the only state
that's actually unsafe is `"running"`.

Priority itself is a relative scheduling weight ("polled every Nth poll cycle"), not a documented
number of seconds — the mapping to real-world cadence depends on total bus load and participant
count, so treat it as relative ordering only.

### Enum representation is inconsistent, and writes differ from reads

Whether an enum arrives as a decoded name or a raw number is **not predictable from its declared
type**. Live: `mc/OperatingMode` reads `low` while `mc/CoolingOperatingModeHc2` reads `1`,
`mc/CoolingRequestHc2` reads `0` and `ehp/Hc1Pump` reads `0` — yet `ebusctl` decodes all of them to
names.

A second, config-VERSION-dependent risk on top of that: an older ebusd config generation (the
frozen `archived/` tree, not the currently-served one) leaves `ehp/Status` field 3 unnamed (type
`hcmode2`) with an enum lacking `1=cooling`, so cooling would arrive as a raw `1` on that
generation. **Confirmed NOT present in the currently-published config** — `hcmode2` does not
appear anywhere in `https://ebus.github.io/de/vaillant/*.csv`; field 3 there is cleanly named
`hcmode` with the full `0=off;1=cooling;3=heat;4=water` enum. Which generation this specific
ebusd instance actually runs is unconfirmed from here — the dual-form parsing stays in place as
cheap insurance either way.

- **Every enum read accepts both forms**, mapping through one table; unmapped → `unknown`.
- **Writes take names** (`low`, `on`). Never echo a normalised read back on a write.
- Field *position* is stable across config generations even where field *names* are not, which is
  the one place positional parsing beats named access.

### Register decodes

`ehp/Status` = `HcFlowTemp;HcPress;SourcePress;hcmode;hex` — confirmed by exact value match against
the standalone registers (`25.19;1.266;1.682;off;00`). `hcmode`: `0=off 1=cooling 3=heat 4=water`.

`ehp/HcReturnTemp` (register `0A00`, internal sensor T5) = `temp;sensor` where sensor is
`ok|circuit|cutoff`. Reads on demand; ongoing polling is now registered automatically (priority 3)
by `automation.heating_ebusd_poll_registration` in `packages/heating_pv_boost.yaml` rather than
needing a manual `?5` publish — see that automation and the "Poll-priority registration" section
below. Not yet live-confirmed to actually publish as a result — whether `ebusd/#` reaches HA's
broker at all is still an open item in `plans/ebusd-pv-heating-optimization.md`'s Status
checklist, so the mechanism changed but the outcome isn't verified yet.

`mc/Status0a` = `flowtemp;mixer;pump;onoff;flowtempdesired`.
`mc/Status` = `flowtempdesired;onoff;flowtemp;tempdesired` — no modulation field; field 3 is a
second setpoint, not a percentage.
`hwc/Status` = `desired;onoff;actual;desired`.

**Unusable:** `mc/Mode` field 5 decodes `pool` while both `mc/CfgHeatSinkType` and `mc/Params` say
`mixer` — do not use `mc/Mode` at all. `ehp/Status02` returns placeholder data
(`disabled;0;100.0;0;100.0`).

`ehp/Status01` is **not undefined** — the live config defines it fully: `temp` (flow),
`temp_1` (**return** temperature — an independent alternative to `ehp/HcReturnTemp`), `temp_2`
(outside), `temp_3` (hot water), `temp_4` (storage), `pumpstate`. This specific EHP unit returns
a hardware timeout when it is polled (`ERR: read timeout` in the live dump) — the message exists
and is well-formed, this unit just doesn't answer it. Worth an occasional re-check rather than
writing it off permanently: if it ever responds, `temp_1` is a second, independently-addressed
return-temperature reading.

### Hardware limits the controller must respect

- **`ehp/TimeBetweenTwoCompStartsMin` = 1200 s.** The compressor cannot restart within 20 minutes,
  so no hysteresis may be shorter than that — a faster toggle cannot cycle the machine and only
  adds bus traffic, wear and misleading traces. (`TimeCompOffMin` 300 s, `TimeCompOnMin` 240 s.)
- **No buffer tank.** `uih/EhpHeatBufferAvailable` is `off` and both storage sensors read `cutoff`.
  The slab is the only thermal store, which is why `ehp/HcReturnTemp` reads on its charge state.
- **Resistive backup exists.** `ehp/BackupType` = `internalheatandwater`, currently `no_backup` on
  both circuits. It delivers roughly a quarter of the heat per kWh that the compressor does, so
  never spend PV surplus while `ehp/Backup` is on.
- Thermal ceilings are hardware protections, not tuning targets: `mc/FlowTempMax` 35 °C,
  `mc/FloorProtectionLimit` 44 °C, `ehp/ReturnTempMax` 46 °C, `mc/OtShutdownLimit` 15 °C.
- **No electrical-power or modulation register.** `ehp/Comp` is plain on/off and
  `ActualEnvironmentPower` is thermal display data ("only for graphic display" upstream), so
  `sensor.heizung_power` (Shelly Pro 3EM) is the only real electrical measurement.

### Heating and cooling are separate mode axes

`mc/OperatingMode` is *"Betriebsmodus **Heizen**"* — heating only. Cooling has its own register,
`mc/CoolingOperatingModeHc2`. Writing the heating mode therefore cannot disturb cooling.

Cooling activates in three stages, and the distinction matters:
`mc/CoolingOperatingModeHc2` is a writable **setting** (reads `On` through summer);
`uih/CoolingDemand` is the raw need; `mc/CoolingRequestHc2` is the gated, actually-triggered one
(*"abhängig von der Kühlungsbetriebsart, Zeitfenstern und Effizienzfunktionen"*). Use the activity
signals as interlocks — **never block on the setting**, which would disable heating permanently if
it is not maintained seasonally.

Cooling is released on outdoor temperature, not room setpoint:
`mc/OtShutdownLimit` + `mc/CoolingStartOffsetHc2` = 15 + 2 = 17 °C **outdoor**. So writing
`mc/TempDesired` does not move the cooling threshold. `mc/EfficiencyHysteresisHc2Min` (1.0) is a
flow-to-room delta for *releasing* cooling, not a heating-band constraint.
`DWMOffToCoolingDelayHc2` / `DWMOffToHeatingDelayHc2` are both **6 hours** — the machine enforcing
the same slow-slab logic that makes daily changeover pointless.

### `mc/TempDesiredLow` is the only human knob

Everything HA writes is derived from it, so `mc/TempDesired` set at the wall will be overwritten.
`mc/RoomTempOffset` is write-only (confirmed — only a `w` entry exists, no `r`; visible on MQTT
only because ebusd passively decodes the VR 90 writing it) and so is unusable as a lever.

**Do not confuse `mc/RoomTempOffset` (`b505 2d`, "Raumaufschaltung") with `rcc/RoomTempOffset`
(`1f00`, "Raumisttemp. Korrekturwert") — two different registers on two different circuits that
happen to share a name.** The `rcc` one calibrates the VR 90's own sensor reading (small install-
level constants; live 0.50, alongside `RoomTempOffsetSelfWarming` −2.00). The `mc` one is the
actual room-influence signal feeding the flow-setpoint computation — the one that matters here.

**CORRECTION (superseding an earlier note in this section): a "Raumaufschaltung: off/thermostat"
toggle does exist on this installation and is ebus-communicated — confirmed directly by the owner,
who switches it from both the VR 90 menu and the geoTHERM's own panel.** An earlier version of this
note claimed room influence "has no mode selector" and is structurally additive-only; that claim
was reasoned from the register catalog alone and is now known to be incomplete, not the toggle's
non-existence.

**The toggle itself is not a separate cataloged register.** An exhaustive re-search of the live
GitHub Pages CSVs (`mc`, `ehp`, `uih`, `rcc`, `hwc`, `cc`, `broadcast` — refetched fresh, not the
stale local clone) for `aufschalt`, `thermostat`, `raum*`, and every `UCH`/enum field on all six
circuits found exactly one register whose comment literally says "Raumaufschaltung":
`mc/RoomTempOffset` (`b505 2d`, write-only, plain signed `D2C` °C value, no enum, no mode flag —
see above). Nothing else in the public catalog matches. Two explanations fit the evidence:

1. **Most likely**: "off"/"thermostat" is a VR 90-side (and mirrored geoTHERM-panel-side) menu
   selection that governs *whether the VR 90 writes to `mc/RoomTempOffset` at all*, not a separate
   discrete register — "off" means the VR 90 never sends a correction (or sends a fixed neutral
   one); "thermostat" means it actively trims the flow setpoint from its own room reading. This
   fits the register's shape exactly (a continuous additive correction is precisely what a
   "thermostat trim" would ride on) and needs no undocumented message to exist.
2. **Possible but unconfirmed**: the toggle is a genuine installer-level parameter that the
   community catalog simply never captured, because these CSVs are reverse-engineered from typical
   runtime traffic and installer-menu-only parameters are exactly what such catalogs miss.

**Not yet live-verified which of the two is true, or which value this installation currently has.**
The only way to settle it from here is a live test: watch `ebusd/mc/RoomTempOffset` on MQTT (or
`ebusctl read -f -c mc RoomTempOffset`) while toggling Raumaufschaltung on the real hardware, to see
whether the write starts/stops appearing, or a completely different message ID shows up instead.

**What this means for the plan.** If "thermostat" is the current setting, the VR 90's own
room-based trim could write a compensating correction through `RoomTempOffset` as the room warms
during a slab boost — partially undercutting the very over-charge the boost is trying to achieve,
which is exactly the concern the original (pre-verification) reference plan's Task 3.1 was reacting
to. But this design already does not use or need room-sensor trim: bedrooms are permanently
hydraulically throttled and Loxone's `warm_enough` boolean is the sole comfort input the design
honours (see the plan's "Rejected alternatives" section) — so "thermostat" mode's room compensation
is redundant with this architecture even outside a boost, not merely inconvenient during one. The
pragmatic resolution folded into the plan: set Raumaufschaltung to **off** as a one-time Vaillant/VR
90-side change, alongside setting a real `mc/TempDesiredLow` (see the plan's "Changes outside this
repo"). That removes the interference at the source and needs no new HA-side register write. If the
owner wants room trim active during *normal* (non-boost) operation and only suppressed during a
boost, HA would need to toggle the setting itself — which requires first identifying its literal
ebus write, not yet found, and would need a live capture during an actual toggle to catch it.

Practical consequence either way: raising `mc/TempDesired` during a boost overcomes an additive
`RoomTempOffset` correction by construction (it is additive, not a hard ceiling), so even without
resolving this, a boost is not blocked — only possibly less effective for as long as "thermostat"
stays on. Not bounded, though — no declared max on `RoomTempOffset`'s magnitude was found; observed
live values are small (0.00), but that is observation, not a guarantee.

Holiday mode is unused on this system (`rcc/HolidayPeriod` and `rcc/RoomTempHoliday` both exist
and are confirmed-present registers, but the live dump shows 2015 dates — never actively set).

**`mc/Party` ("Quick - Party", `b505 05`, write-only) does exist in the register catalog** —
confirmed present in the live config, on `mc`, `hwc` and `cc` alike. What doesn't exist is a
physical control for it: the VR 90 has no Party button, confirmed directly against this
installation. So the register is real but untriggerable from the wall on this hardware — recorded
this precisely (rather than "no such register") so a future reader doesn't rediscover `mc/Party`
in a scan and wrongly conclude this note was mistaken.
