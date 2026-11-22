# Vaillant geoTHERM exclusiv VWS 83/2: device reference

Only the unit, independent of HA. Format and evidence tags: `.claude/rules/devices.md`.

## Identity

| Item | Value |
|---|---|
| Prefix | VWS |
| Maker, model | Vaillant geoTHERM exclusiv VWS 83/2, brine-to-water heat pump with built-in hot-water tank and passive cooling [IA p.63] [IA p.7] |
| Article / part no. | 0010002787 [T1] |
| Firmware / controller | `EHP00`, `SW=0383 HW=7201` [T1] |
| Interface | eBUS; heat pump answers at 08 / 23 / 25 / 50 with circuits `ehp`, `cc`, `hwc`, `mc` [T1] |
| Bus participants | 15 control interface `UIH00` (circuit `uih`); 75 VR 90/3 remote control, art. 0020040079 (circuit `rcc`); 05 VR 920 internet module, art. 0020252922, no circuit [T1], dormant [T38]; no VRC 700, no `700` circuit [T1] |
| Hydraulic plan | number unconfirmed (`behaviour.md` Open questions); no buffer, VF2 fitted [T38]. Trap: IA offers only plan 6 (no buffer; sensors AF, SP, VF2) and plan 8 (buffer) [IA p.45] [IA p.63] and equates "ohne Pufferspeicher" with plan 6 [IA p.46] [IA p.48], yet names plans 1, 3 and 4 elsewhere [IA p.48] [IA p.68] [IA p.69]: the manual contradicts itself, so "no buffer" does not settle the number |
| Installed | heats the underfloor slab directly, no buffer, so the slab is the only thermal store; outdoor sensor on the north side without sun [T38]; built-in hot-water tank [IA p.7] |

## References

| ID | Kind | Document (title, doc no., edition, language) | Covers | Where |
|---|---|---|---|---|
| BA | manual | Bedienungsanleitung geoTHERM exclusiv VWS (VWS 63/2, 83/2, 103/2), 0020025604_00, 02/2007, DE; the owner's printed copy matches | frost protection p.10; room setpoint 45° shift p.18; heating curves diagram p.21 | https://kontakt.vaillant.de/documents/download/73792/ (PDF) |
| IA | manual | Installationsanleitung geoTHERM exclusiv VWS, 0020045204_01, 07/2008, DE | passive cooling p.7; hydraulic plans Tab. 7.1 p.45; operating modes, frost protection, floor protection p.46; cooling days p.47; energy balance p.48-49; code level (menus C, D, I, A need the installer code to change) p.49; menu 1 status texts p.54; menu C2 p.58; C4/C5 p.59; backup start, C9 Legionellenschutz p.60; installer menu A2, type table p.63; calibration p.65; vrDIALOG parameters Tab. 8.7 p.68-69 (Art HK2 p.68; FlowTempMax, hysteresis, starts/h, ReturnTempMax, max heating/charging time p.69) | https://kontakt.vaillant.de/documents/download/73782/ (PDF, text layer) |
| IA0 | manual | Installationsanleitung geoTHERM exclusiv VWS, 0020045204_00, 02/2007, DE (earlier revision of IA) | only menu C9 p.59: frost delay 0–12 h, factory 1 h, and Temp.überhöhung; IA (_01) has no frost-delay menu (its C9 p.60 is Legionellenschutz) | https://kontakt.vaillant.de/documents/download/73781/ (PDF) |
| IA3 | manual | Installationsanleitung geoTHERM exclusiv VWS 63/3-103/3, 0020087974_00, DE: sibling /3 model, cite only where the /2 documents are silent | frost protection end 4 °C p.58; 0.1 heating curve p.66; Raumaufschaltung Thermostat p.68. The site refuses plain `curl`; a browser user agent works | https://kontakt.vaillant.de/documents/download/78824/ (PDF) |
| CAT | catalog | ebusd published configuration (served CSVs, never the `archived/` ones) | `08.ehp.csv` (ehp), `50.ehp.mc.csv` (mc, incl. pump registers), `15.uih.csv` (uih), `broadcast.csv`; decodes only | https://ebus.github.io/de/vaillant/ (CSV) |
| EBD | software | ebusd wiki, "MQTT client" and "TCP client commands" pages (unversioned wiki, read 2026-11; ebusd ≥ 24.1 here, exact version unconfirmed) | MQTT: topic layout, `/get` with `?N` poll priority, `/set` writes, `ebusd/global/*` topics (`running` with last will, `scan`, `version`, `uptime`, `signal`), `--mqttjson`; TCP: `find` (prints cached values) vs `read -f` (forced bus read) | https://github.com/john30/ebusd/wiki/3.3.-MQTT-client, https://github.com/john30/ebusd/wiki/3.1.-TCP-client-commands (HTML) |
| MOSQ | software | mosquitto.conf(5) man page (current online edition; broker version: the HA Mosquitto app) | bridge `topic` direction (`in` imports, `out` exports, default `out`); bridge settings reloadable but applied only when the bridge reconnects | https://mosquitto.org/man/mosquitto-conf-5.html (HTML) |
| KF | forum | André Kühne, heating-curve formula for Vaillant sensoCOMFORT curves (OpenEnergyMonitor forum), write-up 2024-10-18 | formula and constants | https://protonsforbreakfast.wpcomstaging.com/2024/10/18/vaillant-heat-pump-controls-part-3-formulas-and-spreadsheet/ (HTML) |

## Files

| File | Answers |
|---|---|
| `behaviour.md` | what the unit does (modes, cooling, outdoor value; index of `runs.md` and `protections.md`); its settings; what steers it (`## Control`) and what does not (`## Does not work`); open questions |
| `interface.md` | how it is reached (ebusd over MQTT: config, polling, writes, bridge wiring, quirks); index of the register parts `registers-ehp.md`, `registers-mc-uih.md`; what this unit does not answer |
| `evidence.md` | every test on this unit (T rows) |
| `heating-curve.md` | read when reasoning about the flow setpoint: curve diagram, table, formula, how closely this unit follows it |

## Used by

- `heating_pv_boost`: `doc/heating_pv_boost/notes.md` (how the package reads and writes the unit)
