---
paths:
  - "doc/devices/**"
---

# Device docs (`doc/devices/<device>/`)

The single home of the device-doc format. Home and boundary with packages:
`doc/KNOWLEDGE.md#K-9`; workflow: `device-knowledge` skill; skeleton: `doc/devices/_template/`.

## Files (one home per topic inside the device)

| File | Holds |
|---|---|
| `README.md` | identity (maker, model, article no., firmware, interface and address, where installed), `## References`, file map, packages using it (pointers to their notes) |
| `behaviour.md` | only the unit, never HA: states, sequences, protections; `## Control` (levers that steer it: effect, limits); `## Does not work` (levers tried or documented that do not steer it, and what happens instead); `## Open questions` (pointers to `plans/…` or `#n` only) |
| `interface.md` | transport, addressing, polling limits; register/API definitions (name, decode, unit, access, evidence); `## Unusable on this unit`. Registers are defined here only, named elsewhere |
| `evidence.md` | the T table: tests on this unit (`evidence-archive.md`: rows no fact cites, K-1.2) |
| `<topic>.md` | optional, one self-contained topic (e.g. a curve table); listed in the README file map with its read-when condition (K-1.3) |

## Evidence tags: every fact carries one; untagged = a bug

| Tag | Means | Grade |
|---|---|---|
| `[<REF> p.<n>]`, `[<REF> §<n>]`, `[<REF>]` | a row of README `## References`, ID `<REF>` (uppercase) | by its Kind: `manual`, `datasheet`, `vendor` = DOC; `catalog` = DOC for decodes only; `forum` = UNPROVEN |
| `[T<n>]` | tested on this unit, row `T<n>` of `evidence.md` | that row's grade |
| `[ASSUMED]` | our reading, no source, no test | UNPROVEN; only where something relies on it, the settling test is a `plans/` step |

- One source per bracket: `[IA p.63] [T4]`.
- This unit beats the manual. On conflict keep both: `X [IA p.63]; this unit does Y [T5]`.
- A manufacturer default and this unit's value are separate facts with separate tags.
- References columns: `ID | Kind | Document (title, doc no., edition, language) | Covers | Where`
  (download URL, or the local copy under `references/`, never edited).

## Fact IDs

- Prefix: README Identity row `| Prefix | VWS |`, uppercase, repo-unique, never a design-doc prefix.
- Only a fact cited from outside this folder gets an ID `<PREFIX>-<n>`: a table row in its first
  cell (ID column), a bullet as a leading `**VWS-<n>**`. Never renumber; retire like a design ID
  (`doc/KNOWLEDGE.md#K-4`).
- Outside the folder cite `(device VWS-7)`. Text next to an anchor that restates the fact is a copy
  (K-6 exception).

## evidence.md rows

`| T<n> | <YYYY-MM-DD or YYYY-MM> | <method> | <what was seen> | CONFIRMED or OBSERVED |`
- Method says how, so it can be repeated: forced `ebusctl read`, write + read-back, panel menu
  read by the owner, HA history query; name the unit if several.
- Numbers are never reused, rows never deleted; a contradicting row says `contradicts T<n>`.
- A row exists because a fact cites it: evidence, not a work log.

## Graduation

`[ASSUMED]` or `forum` fact → `plans/` step with the test (UNPROVEN) → test → T row → replace the
tag. OBSERVED → CONFIRMED only with a new T row (repeat, mechanism shown). A disproved fact is
rewritten citing the new row; a lever that failed moves to `## Does not work`. An entry leaves
`## Does not work` only with a T row showing it works (move it to `## Control`, cite both).

## Content

Current state only (no "was", "no longer"). No entity ids, automations or package decisions.
Changing or disproving a fact that has an ID: `grep -rn '<ID>\b' doc packages plans tests custom_templates`;
re-read every hit and make each copy agree or delete it; for each design hit apply K-4 "Rests on".
Never edit a cited fact without that grep.
`.github/scripts/check_knowledge_layout.py` enforces the format above (files, headings, tags, T
rows, IDs, size caps K-1.2).
