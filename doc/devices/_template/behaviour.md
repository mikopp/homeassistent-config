# <Maker> <Model>: behaviour

> **TEMPLATE.** See `README.md` in this folder.

Only the unit, never HA. Registers are named here, defined in `interface.md`. Every statement
carries an evidence tag (`.claude/rules/devices.md`).

## States and sequences

- <state or sequence> [<REF> p.<n>] [T<n>]

## Control

| Lever (menu, register, input) | Effect | Limits | Evidence |
|---|---|---|---|
| <lever> | <what the unit does> | <range, delay, side effects> | [<REF> p.<n>] [T<n>] |

## Does not work

| Lever tried | What happens instead | Evidence |
|---|---|---|
| <lever and value> | <ignored, refused, other effect> | [T<n>] |

## Open questions

- <question>: `plans/<feature>.md` step <n>
