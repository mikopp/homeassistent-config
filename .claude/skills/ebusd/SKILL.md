---
name: ebusd
description: Reading the eBUS live with ebusctl — the Vaillant geoTHERM heat pump, heating circuit, flow/return/outdoor temperature, mode, setpoint, compressor, any ebus or ebusd register. Use when a heating plan or question needs a current value straight from the heat pump, to check that a register answers, or to list ebusd messages. Read-only; any write needs the owner's consent first.
---

# Reading the eBUS with ebusctl

Register decodes and what the unit answers: `doc/devices/vaillant-vws-83-2/README.md` (file map).
Command syntax: its `EBD` References row.

## Allowed without asking

Only these two forms, run from the repo root:

```
.claude/skills/ebusd/scripts/ebusctl -- read [-f] [-c CIRCUIT] [-v|-V] [-n|-N] NAME [FIELD]
.claude/skills/ebusd/scripts/ebusctl -- find [-v|-V] [-r|-w|-p|-a|-d|-e] [-c CIRCUIT] [NAME]
```

- Always put `--` before the ebusd command; ebusd flags before it are rejected. Allowed before it:
  `-t SECS`, `-e` only.
- `read -f` queries the unit; `read` without `-f` and `find` return the cache. Test whether a
  register answers with `read -f`.
- Keep `read -f` sparse (each is a bus telegram). For series use HA history (ha-mcp).
- Answers are `;`-separated positional fields; `ERR: ...` means failure.

## Never without the owner's consent

Consent means a yes in chat for this exact command, asked before running it, saying what it
changes. A permission prompt is not consent: stop and ask in chat first.

- Any ebusd command other than the two forms above: `write`, `hex`, `inject`, `answer`, `auth`,
  `define`, `scan`, `reload`, `log`, `raw`, `dump`, `grab`, `listen`, `direct`, `quit`, and
  `read -h`, `read -def`, `read -p`.
- Any write to the bus by another path: MQTT `/set`, an HA service, `nc` or another client.
  ha-mcp stays read-only.
- Changing, moving or deleting anything under `.claude/skills/ebusd/` or the ebusctl rules in
  `.claude/settings.json`, by any means.
- Working around the allowlist in any way (other script path, shortcut letters like `r`/`w`).

## Never at all

- Find out, guess, ask for or record the ebusd host or port, by any means: files, script options
  (`-s`, `-p`), command output, ha-mcp, DNS, network tools, scanning.
- Open, read, list, copy or search any file in `.claude/skills/ebusd/` other than `SKILL.md`
  (running the script is fine; reading it is not).
- Repeat or record a host, address or port that appears in any output.

## When it fails

Connection refused, unknown host or timeout: tell the owner ebusd is not reachable from here and
stop. No retry loop, no troubleshooting of the connection.

## After reading

A value read for a plan goes into the plan step that needed it. A new fact about the unit goes
through `device-knowledge` and `record-learning`, never straight into a note.
