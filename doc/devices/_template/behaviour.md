# <Maker> <Model>: behaviour

> **TEMPLATE.** See `README.md` in this folder.

Only the unit, never HA. Registers are named here, defined in `interface.md`. Every statement
carries an evidence tag (`.claude/rules/devices.md`). Over its cap (K-1.2) a subsystem moves to
`<topic>.md` (first line: what it covers, `indexed by behaviour.md`); this file keeps a States
summary with one `<topic>.md — read when <decision>` line per part, and the three sections below.

## States and sequences

- **<PFX>-<n>** <state or sequence> [<REF> p.<n>] [T<n>] (ID only when cited from outside)

## Control

| ID | Lever (menu, register, input) | Effect | Limits | Evidence |
|---|---|---|---|---|
| <PFX>-<n> | <lever> | <what the unit does> | <range, delay, side effects> | [<REF> p.<n>] [T<n>] |

## Does not work

| ID | Lever tried | What happens instead | Evidence |
|---|---|---|---|
| <PFX>-<n> | <lever and value> | <ignored, refused, other effect> | [T<n>] |

## Open questions

- <question>: `plans/<feature>.md` step <n> or `#<n>`
