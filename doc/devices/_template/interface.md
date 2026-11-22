# <Maker> <Model>: interface

> **TEMPLATE.** See `README.md` in this folder.

The single home of register/API definitions for this unit; what the unit does with them is in
`behaviour.md`.

## Transport

- <bus, gateway, address, polling or block-size limits> [<REF> p.<n>] [T<n>]

## Registers

| ID | Register / path | Decode (fields, type, unit) | Access | Evidence |
|---|---|---|---|---|
| <PFX>-<n> | <name> | <fields> | r / w / rw | [<REF>] [T<n>] |

## Unusable on this unit

| ID | Register / path | Problem (timeout, placeholder data, write-only, wrong label) | Evidence |
|---|---|---|---|
| <PFX>-<n> | <name> | <problem> | [T<n>] |
