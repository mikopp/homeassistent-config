---
paths:
  - "packages/**/*.yaml"
  - "automations.yaml"
  - "scripts.yaml"
  - "configuration.yaml"
  - "blueprints/**/*.yaml"
  - "custom_templates/**"
  - "dashboards/**"
---

# Code comment style (YAML `#` and Jinja `{# #}`)

The one home of this style (`doc/KNOWLEDGE.md#K-5` points here). Where a fact goes instead of a
comment: `doc/KNOWLEDGE.md#K-1.1`, only when you are about to record one.

- Each comment says **what** the block does, at most **one line of why**, and a pointer for more:
  `# → doc/<pkg>/design.md#PG-4` or `# → doc/<pkg>/notes.md`.
- No dates, no stories, no "was changed because": that is git history or background.
- The automation `description:` is the human summary shown in the HA UI; keep it current.
- **Jinja `{# #}` comments** (inside `state:` / `availability:` / `value_template:` strings and in
  `custom_templates/*.jinja`) follow the same style: what + at most one line of why, no history
  ("was …", "no longer …", "removed …"), no rule that is written elsewhere. In particular do not
  repeat the "availability guard ⇒ no `float` default" rule (it lives in `.claude/rules/ha-yaml.md`),
  and do not restate a decision table or invariant that a design ID holds: point to it.
- **Automations:** put cross-cutting rules (edge rules, single-decision, guard invariants, hardware
  facts) once in design/notes and give each trigger / branch a one-line comment with `→ #ID`.
  Never paste the same rule into several blocks.
- Jinja comments are template text, so editing them changes the YAML data tree. Check a
  comment-only template edit with `.github/scripts/yaml_semantic_equal.py --ignore-jinja-comments
  <ref> <files>` (render-equivalence: comments and whitespace ignored, code must be identical).
  Plain `yaml_semantic_equal.py` (no flag) is for YAML `#` comments only and fails on any Jinja
  comment change. Behaviour changes are never "comment-only": they need tests.
