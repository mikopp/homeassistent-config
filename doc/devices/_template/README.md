# <Maker> <Model>: device reference

> **TEMPLATE.** Copy this folder to `doc/devices/<maker>-<model>/` (`device-knowledge` skill),
> then delete this banner and every `<placeholder>` row. Never cite the template.

Only the unit, independent of HA. Format and evidence tags: `.claude/rules/devices.md`.

## Identity

| Item | Value |
|---|---|
| Prefix | <PFX> (fact IDs `<PFX>-<n>`, repo-unique) |
| Maker, model | <maker> <model> [<REF> p.<n>] |
| Article / part no. | <no.> [T<n>] (type plate) |
| Firmware / controller | <version> [T<n>] |
| Interface | <bus or protocol, gateway, address> [T<n>] |
| Installed | <where, what it serves> |

## References

| ID | Kind | Document (title, doc no., edition, language) | Covers | Where |
|---|---|---|---|---|
| <REF> | manual | <title>, <doc no.>, <edition>, <lang> | <models, chapters> | <download URL> or `references/<file>` |

Kinds: `manual`, `datasheet`, `vendor` (maker's statement), `catalog` (register definitions),
`forum` (third party, weak).

## Files

| File | Answers |
|---|---|
| `behaviour.md` | what the unit does; what steers it (`## Control`) and what does not (`## Does not work`) |
| `interface.md` | how to talk to it; register/API definitions; what this unit does not answer |
| `evidence.md` | every test on this unit (T rows) |

## Used by

- `<package>`: `doc/<pkg>/notes.md` (how the package uses the unit)
