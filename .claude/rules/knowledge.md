---
paths:
  - "doc/**/notes.md"
  - "doc/**/design.md"
  - "doc/**/tests.md"
  - "doc/KNOWLEDGE.md"
  - ".claude/rules/**"
  - ".claude/skills/**"
  - ".claude/commands/**"
---

Before you create, change, move or delete knowledge here (a note, rule, skill, command or design
doc), read `doc/KNOWLEDGE.md` first: homes and the four kinds always / rule / skill / reference (K-1),
note vs YAML comment vs design doc (K-1.1), size caps (K-1.2), splitting a reference into
indexed parts with read-when pointers (K-1.3), design-doc rules and gate (K-4, K-4.1), extending
(K-6), loading checks (K-7).
Record learnings only through the `record-learning` skill.
A line ending `(device <ID>)` copies or cites a device fact: before changing it, read that fact in
`doc/devices/`; change the source first, then the copy.
