# <Maker> <Model>: interface

> **TEMPLATE.** See `README.md` in this folder.

How this unit is reached and what it answers, independent of the packages using it; what the unit
does with a register is in `behaviour.md`. No entity ids (the package note's entity map maps
entity → register). Generic behaviour of the program or integration is cited by a `software`
References row, never restated. Over its cap (K-1.2) the registers move out first, then an access
path (`.claude/rules/devices.md` Parts).

## Access

<!-- One block per access path while small; once split, one line per part:
`access-<path>.md` — read before <decision> (polling, writes, wiring, a new register). -->

- **<path>** (<bus or protocol>, <gateway or adapter>, <program or HA integration, version>,
  config source <catalog or file>): addressing <address, circuit, unit id> [T<n>]; the rest of the
  path in `access-<path>.md` (template `access.md`) or below while this file is small.

## Registers

<!-- Small device: the table here. Split: one line per part, e.g.
`registers-<area>.md` — read before adding or parsing a register of <area> (<circuit or address range>). -->

| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |
|---|---|---|---|---|---|
| <PFX>-<n> | <name or address> | <fields, type, scale, unit> | <range; enum `0=off 1=on`, both forms if the path delivers both> | r / w / rw | [<REF>] [T<n>] |

## Unusable on this unit

| ID | Register / path | Problem (timeout, placeholder data, write-only, wrong label) | Evidence |
|---|---|---|---|
| <PFX>-<n> | <name> | <problem> | [T<n>] |
