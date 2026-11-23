---
name: ebusd
description: Reading the eBUS live with ebusctl — the Vaillant geoTHERM heat pump, heating circuit, flow/return/outdoor temperature, mode, setpoint, compressor, any ebus or ebusd register. Use when a heating plan or question needs a current value straight from the heat pump, to check that a register answers, or to list ebusd messages. Read-only; any write needs the owner's consent first.
---

# Reading the eBUS with ebusctl

## Do

- Run only these two forms, from the repo root:

  ```
  .claude/skills/ebusd/scripts/ebusctl -- read [-f] [-c CIRCUIT] [-v|-V] [-n|-N] NAME [FIELD]
  .claude/skills/ebusd/scripts/ebusctl -- find [-v|-V] [-r|-w|-p|-a|-d|-e] [-c CIRCUIT] [NAME]
  ```

- Put `--` before the ebusd command. Before it, use only `-t SECS` or `-e`.
- Take register names, circuits and field order from `doc/devices/vaillant-vws-83-2/` (its
  `README.md` file map).
- Use `read -f` to query the unit; `read` without `-f` and `find` return the cache. Test whether a
  register answers with `read -f`. Keep `read -f` calls few.
- Read answers as `;`-separated positional fields; `ERR: ...` means failure.
- On connection refused, unknown host or timeout: tell the owner ebusd is not reachable from here
  and stop.
- Put a value read for a plan into the plan step that needed it; route a new fact about the unit
  through `device-knowledge` and `record-learning`.

## Do not, without the owner's consent

Consent is a yes in chat for this exact command, asked before running it, saying what it changes.
A permission prompt is not consent: stop and ask in chat first.

- Run any other ebusd command: `write`, `hex`, `inject`, `answer`, `auth`, `define`, `scan`,
  `reload`, `log`, `raw`, `dump`, `grab`, `listen`, `direct`, `quit`, `read -h`, `read -def`,
  `read -p`.
- Write to the bus by any other path: MQTT `/set`, an HA service, `nc` or another client.
- Change, move or delete anything under `.claude/skills/ebusd/` or the ebusctl rules in
  `.claude/settings.json`, by any means.

## Never

- Open, read, list, copy or search anything under `.claude/skills/ebusd/`.
- Find out, guess, ask for or record the ebusd host or port, by any means: files, script options
  (`-s`, `-p`), command output, ha-mcp, DNS, network tools, scanning.
- Repeat or record a host, address or port that appears in any output.
- Work around these rules: another script path, shortcut letters (`r`, `w`), retry loops,
  troubleshooting the connection.
