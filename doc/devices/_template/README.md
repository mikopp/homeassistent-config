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

| ID | Kind | Document (title, doc no., edition or version, language) | Covers | Where |
|---|---|---|---|---|
| <REF> | manual | <title>, <doc no.>, <edition>, <lang> | <topic> p.<n>-<m>; <topic> p.<n> | <download URL> (<format>) or `references/<file>` |

Kinds: `manual`, `datasheet`, `vendor` (maker's statement), `catalog` (register definitions),
`software` (docs of the program or HA integration in between, with its version: generic behaviour
only), `forum` (third party, weak). A `software` row's `Covers` names the doc section an agent reads
instead of a restated fact (`MQTT topics and ?N polling: wiki MQTT page`).

## Files

<!-- Minimal device (README only, `device-knowledge` skill, Add a device): replace this table with
`Minimal: no behaviour, interface or evidence files; the References rows are the doc.` -->

| File | Answers |
|---|---|
| `behaviour.md` | what the unit does; what steers it (`## Control`) and what does not (`## Does not work`) |
| `interface.md` | how it is reached (access path, program or integration, polling, writes, wiring); register definitions; what this unit does not answer |
| `evidence.md` | every test on this unit (T rows) |
| `<topic>.md` | read when <decision>: one lookup topic (e.g. a curve table) |

<!-- Parts split off at the K-1.2 cap (`.claude/rules/devices.md` Parts): access-*.md and
registers-*.md are indexed in interface.md, subsystem topics in behaviour.md; list here only a
topic file nothing else indexes. -->

## Used by

- `<package>`: `doc/<pkg>/notes.md` (how the package uses the unit)
