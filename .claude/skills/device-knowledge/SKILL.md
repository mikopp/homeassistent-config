---
name: device-knowledge
description: Hardware unit facts (heat pump, ventilation, Somfy, Shelly, Victron): adding a device, a test on the unit, a lever that does or does not steer it, a register decode, a manual page; use before writing under doc/devices/ or putting a hardware fact into a note.
---

# Device knowledge

Home and boundary with packages: `doc/KNOWLEDGE.md#K-9`. File roles, evidence tags, T rows and
graduation: `.claude/rules/devices.md`; it loads when you Read any file under `doc/devices/`, so
read the device's `README.md` (or `doc/devices/_template/README.md`) first. Whether a finding is
worth writing and what proves it: `record-learning` sections 0 to 2, plus the device gate below.

## Is it worth writing? (device gate)

A device doc is not a copy of the manual: a fact the References row already answers, cheaply and
plainly, is found there. Record a fact only if at least one holds, and it passes `record-learning`
section 0:

- **Would not be looked up otherwise:** a test on this unit, behaviour the documents are silent
  on, a lever that does not work, a conflict with the manual. An agent cannot know to check.
- **Easy to misread:** the source is ambiguous, contradicts itself, uses a misleading label or
  unit, or hides a condition in a footnote. Write the reading and its tag; one clause says what
  makes it a trap.
- **Expensive to read:** the answer sits in a long PDF, a scanned page, a large catalog or across
  several documents. Write the conclusion with the page tag so nobody reads the source again.

Do NOT record: what a References row's `Covers` pointer already leads to in a short HTML/MD
page; generic knowledge of the device class; values no package or decision uses; restated
manual chapters. Unsure: ask the owner; a skipped fact costs a lookup, a useless one costs
context in every read.

## Device doc or package note?

| Finding | Home |
|---|---|
| the unit's behaviour, a protection, a sequence, a threshold from the manual | device `behaviour.md` |
| a lever that steers the unit, or one that does not | device `behaviour.md` `## Control` / `## Does not work` |
| a register's decode, access, timeout or bogus answer | device `interface.md` |
| a manual, catalog or forum post used as a source | device `README.md` `## References` |
| which entity reads it, why the package uses it, a workaround for a device limit | package note / design, citing `(device <ID>)` |
| a quirk of the software in between (HA integration, ebusd program, MQTT payload) | package note or a skill |
| an untested idea | `plans/` (UNPROVEN), with the test that would settle it |

## Add a device

**Minimal (README only)** when nothing passes the gate yet and the references answer what the
packages need: copy only `_template/README.md`, drop the `## Files` table for the line
`Minimal: no behaviour, interface or evidence files; the References rows are the doc.`, and fill
Identity (`[<REF>]` tags only, no `[T<n>]`), References and Used by. Allowed only if every
reference is stable and agent-readable (rule: Minimal device). Each `Covers` cell says which
topics and pages to read for what (`controls p.12-14; error codes p.40`), so an agent reads one
page, not the document. The first fact that passes the gate makes it a full doc: copy the other
three template files.

**Full:**
1. `cp -R doc/devices/_template doc/devices/<maker>-<model>` (lowercase kebab), then remove the
   template banners and placeholder rows.
2. `README.md`: identity from the type plate, manual and ha-mcp device info (read-only lookups).
   One `## References` row per document, with document number, edition and download URL; give
   each a short uppercase ID (`IA`, `BA`, `CAT`).
3. Fill `behaviour.md` and `interface.md` only with tagged facts. Every lever you know to fail
   goes under `## Does not work` now, not later.
4. Point both ways: the package note header gets a `Device:` line naming each device doc and the
   decision that requires reading it (`behaviour.md` before changing a write to the unit or
   reasoning about how it reacts; `interface.md` before adding a register; a topic file before
   touching its topic), never "read first" (K-3). The device README lists the package. Move
   device facts out of the note; keep at most an anchored one-liner (K-6).
5. Run `.github/scripts/check_knowledge_layout.py`.

## Record a finding

Apply the device gate first; a finding that fails it is not written.

1. A test on the unit: add the next `T<n>` row to `evidence.md` (date, repeatable method, what
   was seen, grade), cite it in the fact, replace the `[ASSUMED]` or forum tag it settles, mark
   the plan step done.
2. A lever did not steer the unit: a `## Does not work` entry saying what was tried (register or
   menu, value), what happened instead, and its tag. A manual saying a lever does not exist counts.
3. A manual fact: add the document to `## References` first, then cite its page.
4. Contradicts a manual: keep both, the unit's behaviour wins (rule: conflicts).
5. The package relies on it: one imperative line in the package note ending `(device <ID>)`;
   give the fact an ID first (rule: Fact IDs).
6. The fact has an ID: run the grep in `.claude/rules/devices.md` §Content before finishing.

## Answer "can X steer the unit?"

Read `behaviour.md` `## Control` and `## Does not work`, then `interface.md`. Answer with the
tags: say whether it is tested here (`T`), only documented (DOC), or assumed. Nothing found =
unknown, not "no".
