---
paths:
  - "doc/devices/**"
---

# Device docs (`doc/devices/<device>/`)

Format. Home and boundary: `doc/KNOWLEDGE.md#K-9`; workflow, gate, minimal device:
`device-knowledge` skill; skeleton: `doc/devices/_template/`.

## Files (one home per topic inside the device)

| File | Holds |
|---|---|
| `README.md` | identity (firmware, interface, where installed), `## References`, file map, Used by |
| `behaviour.md` | states, sequences, protections; `## Control` (lever: effect, limits); `## Does not work` (lever tried, what happens instead); `## Open questions` (`plans/…` or `#n` only) |
| `interface.md` | `## Access`: per path (bus, gateway, program or HA integration, its config) the sections of template `access.md`; `## Registers` (defined here only); `## Unusable on this unit` |
| `evidence.md` | T table: tests on this unit |

No entity ids, automations or package decisions anywhere (K-9). Minimal device: `README.md` alone.

## Parts: caps K-1.2 (12,000; README 8,000; evidence 16,000)

Above the cap split by decision (K-1.3). A part starts with one line: what it covers,
`indexed by <file>`; the index lists it with `read before/when <decision>`.

| Part | Indexed in | Holds |
|---|---|---|
| `access-<path>.md` | `interface.md` | one access path (template `access.md`) |
| `registers-<area>.md` | `interface.md` | register table of one circuit or address range |
| `<topic>.md` | `behaviour.md` (subsystem) or README | one subsystem or lookup topic |
| `evidence-archive.md` | `evidence.md` | rows no fact cites |

`interface.md` moves registers out first, an access path only if still over. Kept:
`interface.md` an access summary and `## Unusable on this unit`;
`behaviour.md` States summary, `## Control`, `## Does not work`, `## Open questions`.
Register rows: `| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |`
(an enum: both forms if the path delivers both).

## Evidence tags: every fact carries one; untagged = a bug

| Tag | Means | Grade |
|---|---|---|
| `[<REF> p.<n>]`, `[<REF> §<n>]`, `[<REF>]` | a README `## References` row, ID `<REF>` (uppercase) | by Kind: `manual`, `datasheet`, `vendor` = DOC; `catalog` = DOC for decodes only; `software` (program or integration docs, pinned version) = DOC for generic behaviour only; `forum` = UNPROVEN |
| `[T<n>]` | tested on this unit, row `T<n>` of `evidence.md` | that row's grade |
| `[ASSUMED]` | our reading, no source, no test | UNPROVEN; only if something relies on it |

- One source per bracket: `[IA p.63] [T4]`. This unit beats the manual; keep both:
  `X [IA p.63]; this unit does Y [T5]`. A maker default and this unit's value: separate facts.
- References: `ID | Kind | Document (title, doc no., edition or version, language) | Covers | Where`
  (URL or `references/` copy, never edited).

## Fact IDs

- Prefix: README Identity row `| Prefix | VWS |`, uppercase, repo-unique, never a design-doc prefix.
- Only a fact cited from outside gets `<PREFIX>-<n>`: first cell of a table row, or a leading
  `**VWS-<n>**` on a bullet. Never renumber; retire like a design ID (K-4). Outside the folder
  cite `(device VWS-7)`; text restating the fact there is a copy (K-6).

## evidence.md rows

`| T<n> | <YYYY-MM-DD or YYYY-MM> | <method> | <what was seen> | CONFIRMED or OBSERVED |`
Method is repeatable (forced read, write + read-back, panel menu); name the unit if several.
Never reuse a number or delete a row; a contradicting row says `contradicts T<n>`. A row exists because a fact cites it (not a work log).

## Graduation and content

`[ASSUMED]`/`forum` → `plans/` step → T row → new tag. OBSERVED → CONFIRMED: a new T row. A failed
lever goes to `## Does not work`, back only with a T row showing it works.
Record only what passes the skill's gate. Current state only. Changing a fact with an ID:
`grep -rn '<ID>\b' doc packages plans tests custom_templates`; fix or delete every copy; a design
hit: K-4 "Rests on". The layout check enforces it.
