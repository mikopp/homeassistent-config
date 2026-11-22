---
paths:
  - "doc/devices/**"
---

# Device docs (`doc/devices/<device>/`)

The device-doc format. Home and boundary: `doc/KNOWLEDGE.md#K-9`; workflow: `device-knowledge`
skill; skeleton: `doc/devices/_template/`.

## Files (one home per topic inside the device)

| File | Holds |
|---|---|
| `README.md` | identity (maker, model, article no., firmware, interface, where installed), `## References`, file map, packages using it |
| `behaviour.md` | only the unit, never HA: states, sequences, protections; `## Control` (levers that steer it: effect, limits); `## Does not work` (levers that do not steer it, what happens instead); `## Open questions` (`plans/…` or `#n` only) |
| `interface.md` | transport, addressing, polling limits; register/API definitions (name, decode, unit, access, evidence), defined here only; `## Unusable on this unit` |
| `evidence.md` | T table: tests on this unit (`evidence-archive.md`: uncited rows, K-1.2) |
| `<topic>.md` | optional self-contained topic (e.g. a curve table); in the README file map with its read-when condition (K-1.3) |

**Minimal device:** `README.md` alone (no other file), when no fact passes the gate (§Content).
Only if each reference is stable (doc no. + edition, or a local copy under `references/`) and
agent-readable: HTML, Markdown or text; a PDF only with a text layer and `Covers` naming the pages
per topic; a scanned PDF never alone. `[<REF>]` tags only. First gated fact: add the other three.

## Evidence tags: every fact carries one; untagged = a bug

| Tag | Means | Grade |
|---|---|---|
| `[<REF> p.<n>]`, `[<REF> §<n>]`, `[<REF>]` | a row of README `## References`, ID `<REF>` (uppercase) | by its Kind: `manual`, `datasheet`, `vendor` = DOC; `catalog` = DOC for decodes only; `forum` = UNPROVEN |
| `[T<n>]` | tested on this unit, row `T<n>` of `evidence.md` | that row's grade |
| `[ASSUMED]` | our reading, no source, no test | UNPROVEN; only if something relies on it; settling test = a `plans/` step |

- One source per bracket: `[IA p.63] [T4]`.
- This unit beats the manual; keep both: `X [IA p.63]; this unit does Y [T5]`.
- A maker default and this unit's value: separate facts.
- References columns: `ID | Kind | Document (title, doc no., edition, language) | Covers | Where`
  (URL or local copy under `references/`, never edited; format if not obvious: HTML, PDF).

## Fact IDs

- Prefix: README Identity row `| Prefix | VWS |`, uppercase, repo-unique, never a design-doc prefix.
- Only a fact cited from outside gets an ID `<PREFIX>-<n>`: first cell of a table row, or a
  leading `**VWS-<n>**` on a bullet. Never renumber; retire like a design ID (K-4).
- Outside the folder cite `(device VWS-7)`; text restating the fact there is a copy (K-6).

## evidence.md rows

`| T<n> | <YYYY-MM-DD or YYYY-MM> | <method> | <what was seen> | CONFIRMED or OBSERVED |`
- Method is repeatable (forced `ebusctl read`, write + read-back, panel menu read by the owner,
  HA history query); name the unit if several.
- Never reuse a number or delete a row; a contradicting row says `contradicts T<n>`. A row
  exists because a fact cites it (not a work log).

## Graduation

`[ASSUMED]`/`forum` → `plans/` step with the test → T row → replace the tag. OBSERVED →
CONFIRMED only with a new T row. A disproved fact is rewritten citing the new row; a failed lever
moves to `## Does not work`, and back to `## Control` only with a T row showing it works.

## Content

Gate: record a fact only if its source would not be checked otherwise, is easy to misread or is
costly to read; never what a `Covers` pointer already answers (`device-knowledge` skill).
Current state only (no "was", "no longer"). No entity ids, automations or package decisions.
Changing or disproving a fact that has an ID: `grep -rn '<ID>\b' doc packages plans tests custom_templates`;
make every copy agree or delete it; for a design hit apply K-4 "Rests on". Never skip that grep.
`.github/scripts/check_knowledge_layout.py` enforces this format.
