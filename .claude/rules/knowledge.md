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

Creating, moving, splitting or deleting knowledge here (note, rule, skill, command, design doc),
or adding a fact: read only the `doc/KNOWLEDGE.md` sections the change needs (index:
`grep -n '^##' doc/KNOWLEDGE.md`): homes and the kinds always / rule / skill / reference (K-1);
note vs YAML comment vs design doc (K-1.1); size caps (K-1.2, `wc -c` the target first);
splitting a reference into indexed parts with read-when pointers (K-1.3); design-doc rules and
gate (K-4, K-4.1); extending, new note/skill/rule (K-6); loading checks (K-7). The whole file
only to change homes, kinds or this layout. A fix that keeps a fact's home and the file under
its cap needs none.
Record learnings only through the `record-learning` skill.
A line ending `(device <ID>)` copies or cites a device fact: before changing it, read that fact in
`doc/devices/` (grep the ID); change the source first, then the copy.
