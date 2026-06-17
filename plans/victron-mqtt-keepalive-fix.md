# Victron MQTT Keep-alive — stop full-tree republish flood

## Problem
The Energy Dashboard host (HA) was receiving thousands of MQTT messages on Victron
topics it never asked for, e.g. `N/c0619ab4c19e/settings`, even though the
keep-alive was meant to request only `solarcharger/279`, `system/0`,
`pvinverter/20`, `vebus/276`.

## Root cause
Modern Venus OS uses the `dbus-flashmq` broker (Venus OS 3.x+), which changed
the keep-alive semantics versus the old `dbus-mqtt-python` implementation:

1. **Selective keep-alive was removed.** Passing a JSON *list of topics* in the
   `R/<portal>/keepalive` payload no longer restricts anything — flashmq ignores
   the list.
2. **Any keep-alive without `suppress-republish` forces a FULL re-publish** of
   every topic on the GX (settings, alarms, every device path, …).

The old automation published a topic-list payload once per minute, so the GX
re-dumped its entire topic tree every 60 s → the flood.

Refs:
- https://github.com/victronenergy/dbus-flashmq (README, keep-alive section)

## Fix (`packages/victron.yaml`)
- **Periodic keep-alive** (`victron_keep_alive_30s`): every 30 s, payload
  `{"keepalive-options":["suppress-republish"]}`. Feeds the 60 s timeout without
  republishing all topics; live value-change updates keep flowing. 30 s interval
  stays comfortably inside the 60 s timeout (old 60 s interval was on the edge).
- **Initial full publish** (`victron_keep_alive_full_publish`): on HA start,
  publish an empty payload once so all sensors populate immediately. After that
  the periodic suppress-republish keep-alive holds the bridge open continuously,
  so the full-tree dump is never requested again.

## Status
- [x] Root cause confirmed against Victron dbus-flashmq docs
- [x] Automations rewritten in `packages/victron.yaml`
- [x] YAML validated
- [ ] Deployed by user via `git pull` on HA host (user action)
