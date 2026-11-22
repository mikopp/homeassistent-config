---
name: device-knowledge
description: Documenting a physical device or hardware unit (heat pump, ventilation unit, Somfy, Shelly, Victron, any hardware): adding a device, recording what a unit did in a test, a control lever that works or does not work, a register or API decode, a manual page or document number, or answering how a unit can or cannot be steered. Use before writing under doc/devices/ or putting a hardware fact into a package note.
---

# Device knowledge

Home and boundary with packages: `doc/KNOWLEDGE.md#K-9`. File roles, evidence tags, T rows and
graduation: `.claude/rules/devices.md`; it loads when you Read any file under `doc/devices/`, so
read the device's `README.md` (or `doc/devices/_template/README.md`) first. Whether a finding is
worth writing and what proves it: `record-learning` sections 0 to 2.

## Device doc or package note?

| Finding | Home |
|---|---|
| the unit's behaviour, a protection, a sequence, a threshold from the manual | device `behaviour.md` |
| a lever that steers the unit, or one that does not | device `behaviour.md` `## Control` / `## Does not work` |
| a register's decode, access, timeout or bogus answer | device `interface.md` |
| a manual, catalog or forum post used as a source | device `README.md` `## References` |
| which entity reads it, why the package uses it, a workaround for a device limit | package note / design, with `(device: <file> <section>)` |
| a quirk of the software in between (HA integration, ebusd program, MQTT payload) | package note or a skill |
| an untested idea | `plans/` (UNPROVEN), with the test that would settle it |

## Add a device

1. `cp -R doc/devices/_template doc/devices/<maker>-<model>` (lowercase kebab), then remove the
   template banners and placeholder rows.
2. `README.md`: identity from the type plate, manual and ha-mcp device info (read-only lookups).
   One `## References` row per document, with document number, edition and download URL; give
   each a short uppercase ID (`IA`, `BA`, `CAT`).
3. Fill `behaviour.md` and `interface.md` only with tagged facts. Every lever you know to fail
   goes under `## Does not work` now, not later.
4. Point both ways: the package note header gets a `Device:` line naming the device docs and when
   to read them; the device README lists the package. Move device facts out of the note rather
   than copying them (K-9).
5. Run `.github/scripts/check_knowledge_layout.py`.

## Record a finding

1. A test on the unit: add the next `T<n>` row to `evidence.md` (date, repeatable method, what
   was seen, grade), cite it in the fact, replace the `[ASSUMED]` or forum tag it settles, mark
   the plan step done.
2. A lever did not steer the unit: a `## Does not work` entry saying what was tried (register or
   menu, value), what happened instead, and its tag. A manual saying a lever does not exist counts.
3. A manual fact: add the document to `## References` first, then cite its page.
4. Contradicts a manual: keep both, the unit's behaviour wins (rule: conflicts).
5. The package relies on it: one imperative line in the package note with the device pointer.

## Answer "can X steer the unit?"

Read `behaviour.md` `## Control` and `## Does not work`, then `interface.md`. Answer with the
tags: say whether it is tested here (`T`), only documented (DOC), or assumed. Nothing found =
unknown, not "no".
