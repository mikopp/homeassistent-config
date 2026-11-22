# <Maker> <Model>: interface

> **TEMPLATE.** See `README.md` in this folder.

The single home of register/API definitions for this unit; what the unit does with them is in
`behaviour.md`.

## Transport

- <bus, gateway, address, polling or block-size limits> [<REF> p.<n>] [T<n>]

## Registers

| Register / path | Decode (fields, type, unit) | Access | Evidence |
|---|---|---|---|
| <name> | <fields> | r / w / rw | [<REF>] [T<n>] |

## Unusable on this unit

| Register / path | Problem (timeout, placeholder data, write-only, wrong label) | Evidence |
|---|---|---|
| <name> | <problem> | [T<n>] |
