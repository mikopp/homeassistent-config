---
name: ebusd
description: Reading the eBUS live with ebusctl (ebusd TCP client) — the Vaillant geoTHERM heat pump, heating circuit, flow/return/outdoor temperature, mode, setpoint, compressor, any ebus or ebusd register. Use when a heating plan or question needs a current value straight from the heat pump, to check that a register answers, or to list ebusd messages. Read-only; any write needs the owner's consent first.
---

# Reading the eBUS with ebusctl

`.claude/skills/ebusd/scripts/ebusctl` is the ebusd project's bash TCP client (upstream copy; one
local change: the default host comes from a config file, see Reaching ebusd). It sends one command line to ebusd's TCP port and prints the answer. What the unit answers,
register decodes and how HA reads it: `doc/devices/vaillant-vws-83-2/README.md` (file map) → its
`interface.md`. Full command syntax: the `EBD` References row there (TCP client commands).

## Read-only: never write without the owner's consent

Allowed without asking (pre-approved in `.claude/settings.json`) — only these two forms, run from the
repo root:

```
.claude/skills/ebusd/scripts/ebusctl -- read [-f] [-c CIRCUIT] [-v|-V] [-n|-N] NAME [FIELD]
.claude/skills/ebusd/scripts/ebusctl -- find [-v|-V] [-r|-w|-p|-a|-d|-e] [-c CIRCUIT] [NAME]
```

Everything else needs the owner's explicit consent **in this conversation, for this exact command**,
asked before running it, saying what it changes. That covers:

- `write`, `hex`, `inject`, `answer`, `auth`, `define`: send to the bus or change definitions.
- `read -h` (raw hex telegram: it can carry any command, also a write), `read -def`, `read -p`
  (changes ebusd's poll priority until restart, device VWS-42).
- `scan`, `reload`, `log`, `raw`, `dump`, `grab`, `listen`, `direct`, `quit`: change or tie up ebusd.
- Writing via MQTT (`ebusd/<circuit>/<name>/set`) or an HA service: same rule. ha-mcp stays read-only.

A permission prompt is not consent: if one appears for an ebusctl call, stop and ask in chat what the
command does and why first. Never work around the allowlist (other script path, `nc` directly,
shortcut letters like `r`/`w`).

## How to call it

- **Always put `--` before the ebusd command.** The script parses its own options with `getopt` and
  rejects ebusd flags otherwise (`ebusctl read -f x` → `invalid option -- 'f'`). Script options
  (`-t SECS`, `-e`) go before `--`; `-s HOST` / `-p PORT` override the config file but are not
  pre-approved, so leave them out.
- `read` without `-f` returns ebusd's cached value (default up to 300 s old); `read -f` queries the
  unit. Test whether a register answers on this unit with `read -f`, not `find` (cache only).
- `find -c ehp` lists a circuit's messages with cached values; `find -V NAME` adds address, last
  update time and message type; `find -w` lists write messages (listing only, writes nothing).
- Circuits on this bus and which registers are unusable: `interface.md` and `README.md` Identity.
- Keep reads sparse: each `read -f` is a bus telegram shared with the controller and VR 90. Prefer
  the cache or HA history (ha-mcp `ha_get_history`) for series; ebusctl is for spot values and
  registers HA does not poll.
- Answers are `;`-separated positional fields (field lists in `registers-*.md`); `ERR: ...` lines
  mean failure (`-e` makes the exit status non-zero on them).

## Reaching ebusd

ebusd listens on TCP 8888 on its host, by default without authentication: anyone reaching the port
can write, so never expose or tunnel it beyond the LAN. A cloud session is not on the LAN and cannot
reach it. The script needs bash, `getopt` and `nc` (Windows: WSL, or Git Bash with netcat).

The host comes from `.claude/skills/ebusd/.ebusctl.conf` (`host=` / `port=` lines, git-ignored, the
owner's local copy of `.ebusctl.conf.example`); without it the script tries `localhost:8888`. Never
commit, create or edit that file, and never write its host into a tracked file. Missing or
unreachable: ask the owner to fill it; do not scan the network. Connection refused or timeout: report it,
do not retry in a loop.

## After reading

A value read for a plan goes into the plan step that needed it, not into a note. A new fact about
the unit (a register answers or times out, a decode, a bogus value) goes through `device-knowledge`
(gate, T row) and `record-learning`; never straight into a note.
