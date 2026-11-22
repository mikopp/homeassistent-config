# Knowledge conventions

How knowledge about this repo is stored for humans and agents. Section IDs (`K-1` …) are stable:
link them as `doc/KNOWLEDGE.md#K-6`, never renumber, mark retired IDs as gone.

## K-1 Where knowledge lives

| Home | What goes there | How it loads | Limit |
|---|---|---|---|
| root `CLAUDE.md` | rules needed in every session (constraints, version gate, MCP, config layout, this table) | always, at session start | < 100 lines |
| `.claude/rules/*.md` | cross-package rules tied to file types (`ha-yaml.md`, `tests.md`; `plans.md` for plan format/status/close; `devices.md` for device-doc format; `knowledge.md`, which sends to this file when knowledge files are touched) | lazily, when a file matching its `paths:` is read | ~4 KB |
| `doc/<pkg>/notes.md` | what an agent must know before editing the package (see K-1.1, K-3) | lazily: the note has its own `paths:` frontmatter and is symlinked as `.claude/rules/packages/<pkg>.md` | ≤ 24 KB |
| `.claude/skills/<topic>/` | cross-package topic knowledge (templates, MQTT, energy, test harness) and workflows (`record-learning`) | on demand, when the task matches the skill description | one topic per skill |
| `doc/<pkg>/design.md` | current architecture: components, decision tables, interfaces, decisions and trade-offs, known gaps, extension points (see K-1.1, K-4) | on demand (read when needed) | aim ≤ 24k, cap 40k chars |
| `doc/devices/<device>/` | one physical unit, independent of HA and of the packages using it: identity, references, behaviour, control (what works, what does not), interface, test evidence (see K-9) | on demand; `.claude/rules/devices.md` loads when a device doc is read | each file aim ≤ 24k, cap 40k chars |
| `doc/<pkg>/background.md`, `doc/sources/<pkg>/` | history, superseded designs, investigations; raw transcripts, spreadsheets | guarded, read only when the user asks for history | none |
| `doc/<topic>/background.md` | the same for a cross-package topic with a skill (e.g. the test framework) | guarded like package background | none |
| YAML comments | what a block does + one-line why + pointer (see K-1.1, K-5) | with the file | short |
| `plans/` | open work and hypotheses only | when working on that plan | deleted when done |
| GitHub issues | confirmed bug or flaky test not being fixed now (repo issues are enabled); link the issue number from the affected note. A plan file is created only when work starts | `gh issue view <n>` | n/a |
| git history / PRs | the log: what changed when and why | `git log`, `gh pr view` | n/a |

Rules:
- **Never use `@` imports in a rule.** They are expanded eagerly at launch, so the imported file is
  always paid for (canary 2026-11-07: an `@` import inside a `paths:` rule loaded at session start).
  The symlink layout (note with its own `paths:` + symlink in `.claude/rules/packages/`) loads lazily.
- **Background and sources are not design-relevant.** Never cite them as current behaviour; read
  them only when the user asks "why/how did this come about".
- **Agent knowledge never refers to background or sources.** Root `CLAUDE.md`, rules, notes,
  skills, design docs, YAML comments and tests must not link, cite or point to
  `doc/<pkg>/background.md` or `doc/sources/` (no "story → background", no "worked example in
  background"). A pointer invites the read the guard exists to prevent. If a fact matters, state it
  where it is needed; if it does not, leave it out. Exempt: this file, the root `CLAUDE.md` homes
  table and the `record-learning` routing table (they name background as a destination, not as
  something to read), the guard in `.claude/settings.json`, and plans that route content there.
  Sources live under `doc/sources/<pkg>/` (one tree, easy to guard), not inside `doc/<pkg>/`.
  Guard (`.claude/settings.json` `permissions.ask`): `Read(/doc/**/background*.md)`,
  `Read(/doc/sources/**)`, `Bash(cat doc/**/background*)`, `Bash(cat doc/sources/*)`.
  Verified headless 2026-11-07: Read and `cat` are blocked; Grep content search is NOT blocked
  (it printed the token), nor are other shell readers. The guard is a prompt, not a wall.
- No dated logs anywhere. Git and PRs are the log.

### K-1.1 Note, YAML comment or design doc?

One home per kind of fact. Ask the question of each home in order; the first "yes" is the home.

| Home | One-question test | Holds |
|---|---|---|
| device doc | Would it stay true if HA were replaced or another package used the unit? | what the hardware is, does, answers and refuses (K-9) |
| YAML comment | Is it about this one block only? | what the block does, at most one line of why, a pointer (K-5) |
| note | Must an agent know it **before editing** this package's YAML or tests? | invariants (one line each), hardware/integration quirks, entity map, decisions in force with a one-line why, owner-supplied values and their origin, open issues (`#n`) (K-3) |
| design doc | Is it needed to **change the architecture**, or to check that an addition does not break it? | components and responsibilities, state machines and decision tables, interfaces/contracts, decisions with rejected alternatives and trade-offs, known gaps, extension points and what breaks them (K-4) |

- **Note vs YAML comment: never both.** A fact local to one block lives in that block's comment;
  the note does not restate it. A fact that spans blocks or is invisible in the YAML (a hardware
  quirk, a cross-block invariant, the reason for an owner value) lives in the note; the blocks
  point to it (`→ doc/<pkg>/notes.md`) instead of restating it.
- **Note vs design doc.** The note auto-loads, the design doc does not. So for anything that
  fails silently when broken, the note keeps the one-line imperative plus `→ design.md#ID`; the
  design doc holds the mechanism, the table and the trade-off behind it, not that line again.
  A decision's why is one line in the note, or chosen/rejected/trade-off in the design doc with
  the note pointing to it: never both in full.
- **Design doc vs implementation.** A design doc may repeat a fact from the note when it needs it
  to be read on its own (a conclusion, not the evidence). It never copies implementation detail.
  Test: *would the sentence need editing if someone renamed an entity, retuned a helper, or
  restructured a template or automation without changing behaviour?* Yes = implementation:
  point to it.

  | Architecture (design doc) | Implementation detail (note or YAML; the design doc points) |
  |---|---|
  | which component decides and which single writer owns each actuator | entity ids, entity maps, helper lists, automation `id`s |
  | the state set, the transitions and the priority order, with why that order | trigger lists, condition-by-condition template text, `float()` defaults |
  | the formula's shape, the derived constant and why it matters | config values and thresholds as such (a helper's tuned number) |
  | contract with another package: what is read/published, unit, sign, availability | register decodes, payload formats, MQTT topics |
  | invariant and the mechanism that keeps it | per-block behaviour already commented in the YAML |
  | how to verify a change (identities that must hold) | test lists, restated test cases |

  Refer to a component by its role. Never write an entity id: HA derives ids from device, area and
  name (`.claude/rules/ha-yaml.md`), so an id is registry state, not design. Name a concept, an
  entity by its name, or the source attribute where it originates (an ebusd register, a Somfy
  property, a Venus OS path). Never a list or map of entities. A number appears only when the design
  depends on it (a derived constant, an oracle table a test asserts against). Point, never copy:
  `(note: Entity map)`, `(note: <section>)`, `(YAML: <automation alias or sensor name>)`,
  `(test: <test name>)`, `→ doc/<pkg>/design.md#ID` between design docs.

  Existing design docs are not rewritten for this alone. Whoever edits a design doc for another
  reason, or finds a mistake in it, also replaces any entity id, entity list or map in the part
  they touch with a role, name or source attribute.

## K-2 Current vs background

- **Current** = what an agent needs to understand or change the package as it runs today:
  behaviour, invariants, formulas in force, hardware facts, entity map, open issues, and decisions
  still in force with a 1-2 line why.
- **Background** = history, CORRECTION/REPOINTED stories, dated STATUS entries, superseded designs,
  step logs, dropped alternatives, investigation logs, derivation work, one-day snapshot values.
- **Sources** = raw material, never edited: LLM transcripts, spreadsheets, raw LLM answers.

Test: *"If background were deleted tomorrow, could an agent still change the package correctly?"*
If no, the fact is current and must not live only in background. A decision in force keeps its
short why in the note or design doc, with no link to background (K-1).

## K-3 Note template (`doc/<pkg>/notes.md`)

Frontmatter `paths:` lists the package YAML, its tests (`tests/ha/test_<pkg>.py`; `tests/e2e/` only when a real-HA test targets the package), and `doc/<pkg>/design.md` if one exists.
Never list background or sources. Sections, in order:

1. Header: scope, rule paths, design-doc link (`doc/<pkg>/design.md`, `<PKG>-*` IDs)
2. Invariants: one line each; when a design ID holds the mechanism, end with `→ design.md#ID`
   and do not restate it (K-1.1)
3. Hardware / integration quirks (graded; a design doc cites them, never copies them). A fact
   about the unit itself lives in its device doc (K-9); the note keeps only what this package
   must do about it, one line with a pointer `(device: <file> <section>)`
4. Entity map (IDs from `default_entity_id` or ha-mcp lookup, never from `unique_id`); the full
   map lives here, never in the design doc
5. Decisions in force (one-line why; no background link)
6. Known biases / open issues (`#n`; the design doc's Known gaps lists the architectural ones by
   `#n`, the note keeps the entry and its grade)
7. Tests: package-specific test facts only (generic harness knowledge is in the `ha-test-harness`
   skill). Above ~2 KB, split into `doc/<pkg>/tests.md` with its own symlink rule and
   `paths:` only `tests/ha/test_<pkg>.py` (plus the `tests/e2e/` files that cover the package, if any).
8. Related

Size: ≤ 24 KB (~6k tokens). Over that, move mechanisms and derivation results to `design.md`
(K-4.1 gate) and stories to background.

## K-4 Design docs (`doc/<pkg>/design.md`)

A design doc holds the **current architecture** of one package (K-1.1): what an agent needs to
change that architecture, or to check that an addition does not break it. Read on demand, never
auto-loaded. No history, no noise. Gate before writing: K-4.1.

- **When:** the package has a state machine, a decision table, derived math, or more than ~800
  YAML lines. Otherwise the note is enough. A package over the threshold without one is a gap:
  open an issue or put it in the next plan for that package.
- **Belongs here:** components and their single responsibility; state machines and decision
  tables in force (priority order and why); invariants with the mechanism that keeps them;
  interfaces/contracts with other packages (read/published, unit, sign, availability); decisions
  in force as chosen / rejected / trade-off accepted; formula shapes and derivation *results*;
  known gaps and accepted risks (each with `#n` or a `plans/` file); extension points (how to add
  X, and what breaks if done otherwise).
- **Does not belong here:** implementation detail (K-1.1 table); history ("was", "no longer",
  "since #n", "pre-#n", "originally"), stories, derivation work, step logs, dated values;
  hardware quirks and measured values (the device doc or the note: cite `(device: <file>
  <section>)` or `(note: <section>)`, use the conclusion);
  cross-package topic facts (a skill); another package's note or design (point to it);
  procedures (resets, deploy steps: a skill or the PR).
- **Grades:** a statement about this repo's config needs none: the YAML wins, fix the doc when
  they disagree. Anything else (device behaviour, HA/upstream semantics, expected physical
  results) carries a grade (`record-learning` section 2), preferably by citing the note or skill
  that holds the graded fact. An owner-chosen rationale is marked `(owner decision)`. An UNPROVEN
  claim stays in `plans/` unless the design works around it; then it goes under Known gaps,
  graded UNPROVEN.
- **IDs:** stable, short, grep-able heading IDs `<PKG>-<n>[.<m>]` (`PG-4`, `AF-7.2`; background
  uses `<PKG>-B<n>`); one prefix per design doc. Never renumber; a new topic takes the next free
  number. Before retiring an ID, grep `packages/ custom_templates/ tests/ dashboards/ doc/
  .claude/` and repoint every hit, then list it on one final line: `Retired: <ID> → <ID>`.
- **Size:** aim ≤ 24k chars, cap 40k (on-demand files are truncated above 40k, K-8). No section
  over ~3k chars: split it or cut.
- **Loading:** never `@`-import it. Add `doc/<pkg>/design.md` to the note's `paths:` so editing
  the design doc loads the note.
- **Template** (sections in this order; omit an empty one):
  1. Header: scope (package files), "YAML wins: fix this doc", link to the note. No status line.
  2. Purpose and boundaries: goals, out of scope, neighbour packages.
  3. Components and data flow: responsibilities, the single writer per output; a diagram only if
     it pays for itself (roles, not an entity list).
  4. State machine / decision table(s) in force.
  5. Formulas and derived constants (results only).
  6. Invariants: mechanism and why it holds (the rule line stays in the note).
  7. Interfaces: inputs consumed, outputs published, contract (sign, unit, availability).
  8. Decisions and trade-offs: chosen / rejected / cost accepted.
  9. Known gaps and accepted risks: `#n` or `plans/…`, grade if not CONFIRMED.
  10. Extension points: how to add a state / input / consumer, and what breaks it.

### K-4.1 Is it worth writing in a design doc?

Write it only if ALL hold:
- An agent making an architectural change, or checking that an addition fits, would decide
  differently without it.
- It is architecture, not implementation (K-1.1 test), and not readable in one place in the YAML
  or tests. A formula stays when its why, its derived constant or its interaction with another
  component is the point; a bare copy does not.
- No note, skill or other design section already holds it (grep the design IDs and the note).
  Point to it instead.
- It is true *now* and needs no date. If the sentence needs "was", "since" or "changed", it is
  history: the PR or background.

Do NOT write:
- Worked examples the tests already pin, unless a test cites the doc as its oracle.
- Entity inventories or helper lists (the note's entity map).
- Procedures (resets, reclaim or deploy steps): a skill or the PR.
- Measured values: the note, graded.
- A second copy of an invariant the note states: the note points `→ design.md#ID` instead.

If unsure, leave it out. A missing paragraph costs one source read; a stale one misleads every
architectural change.

## K-5 YAML comment style

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

## K-6 How to extend

- **New package:** create `doc/<pkg>/notes.md` with `paths:` frontmatter (K-3), then
  `ln -s ../../../doc/<pkg>/notes.md .claude/rules/packages/<pkg>.md` and commit the symlink.
  `<pkg>` in the symlink name is the package YAML name; the folder is `doc/<topic>/` (airflow: `airflow_cooling.md` -> `doc/airflow/notes.md`).
- **Complex package** (K-4 threshold): add `doc/<pkg>/design.md` from the K-4 template and put
  it in the note's `paths:`.
- **New device:** `device-knowledge` skill (copies `doc/devices/_template/`, K-9).
- **New cross-package topic:** a skill in `.claude/skills/<topic>/SKILL.md`; the first words of its
  description carry the trigger.
- **One home per fact.** Every other place points to it; never copy.
- **Every plan's last step:** distil the result into note / design (K-4.1 gate: architecture,
  decisions and gaps only) / skill, move the story to
  background (a package's `doc/<pkg>/background.md`, or `doc/<topic>/background.md` for a
  cross-package topic), update pointers, check the note is ≤ 24 KB, then DELETE the plan.
  `.claude/rules/plans.md` tells plan authors to include this step; the layout check (K-8)
  fails a plan without a Close step.
- Before deleting a fact during a move, confirm the target holds it. Never promote an UNPROVEN
  claim while moving it.

## K-7 Verifying a loading change

Rules are discovered at session start, so verify in a FRESH headless session from the repo root:
`claude -p "<prompt>" --model haiku --allowedTools Read --max-turns 4`. For each changed rule or note:

1. No tools used: the rule's content must NOT be in context.
2. Read one matching file (first lines): the content MUST be in context, and the session names
   the source file.
3. Read one non-matching file (e.g. `README.md`): the content must NOT be in context.

Ask about a distinctive sentence from the rule, not its file name (root `CLAUDE.md` names files).

Skills: run a task prompt that matches the description without naming the skill, with
`--allowedTools Read,Skill,Grep,Glob`; the session must invoke the skill and answer from its body.
A prompt outside the description must not invoke it.

## K-8 Loading mechanics (Claude Code)

What the layout in K-1 relies on. Grades: DOC = Claude Code docs (2026-11-07), CONFIRMED = tested
headless in this repo 2026-11-07 (K-7 method), OBSERVED = real data from a real run with an
alternative explanation still open (same meaning as in `record-learning`).

- Startup loads only root `CLAUDE.md` plus each skill's name + description; no rule or note bodies.
  A skill body loads only when the skill is invoked. (CONFIRMED)
- A `paths:` rule loads when Read/Write/Edit (or a single-file `cat`/`head`) touches a matching
  file. **Grep and Glob do not trigger it**: before relying on package facts after a search, read
  the package YAML or its note. (DOC; Read trigger CONFIRMED)
- Broken frontmatter makes a rule load always. (DOC)
- On-demand files (path rules, nested `CLAUDE.md`, their imports) are truncated above 40k chars.
  (DOC)
- `@` imports in a rule load eagerly at launch; a symlinked note with its own `paths:` loads
  lazily. (CONFIRMED, canary)
- Path rules also load inside subagents (a general-purpose subagent reading `packages/energy.yaml`
  got the energy note and `ha-yaml.md`). (CONFIRMED)
- Guards: `permissions.ask` blocks Read and `cat`, not Grep (K-1). (CONFIRMED)
- Rules are context, not enforcement: anything that must never happen (CRLF, YAML errors) needs a
  check (`.gitattributes`, `ci-local.sh`, CI), not only a rule.
- `.github/scripts/check_knowledge_layout.py` (in `ci-local.sh` and the workflow `.github/workflows/knowledge-layout.yml`) enforces the layout: every
  `plans/*.md` has a `## Status` heading and a Close step, every `packages/*.yaml` has a
  `.claude/rules/packages/<name>.md` symlink to an existing note, every `doc/<pkg>/design.md` is
  ≤ 40k chars, is listed in its note's `paths:` and owns its ID prefix, and every design-ID
  reference (`doc/<pkg>/design.md#ID` or a bare `<PKG>-<n>`) resolves to a heading, and every
  `doc/devices/<device>/` meets the K-9 format checks (`_template` skipped). History
  markers in a design doc are a warning only (until the existing docs are clean). Not yet
  checked: the K-4 template sections (the existing docs lack Known gaps / Interfaces).
- A findings trigger worded "bug or non-obvious fact" missed measured hardware quirks (1/3, haiku,
  3 runs); naming "measured value, hardware quirk, user-supplied reason" gave 3/3. Word findings
  triggers by the concrete case, not the abstract category. (OBSERVED)

## K-9 Device knowledge (`doc/devices/<device>/`)

What a physical unit is and does, independent of HA and of which package uses it: identity,
references (manuals by document number and page, register catalogs), behaviour, how it can be
steered, how it **cannot** (first-class entries, never dropped silently), its interface (registers,
API) and the tests on this unit behind each fact. Generic for any hardware (heat pump, ventilation,
Somfy, Shelly, Victron).

- **One home per fact** (K-1.1 first row). True of the unit whatever HA does = device doc. How a
  package uses the unit (entity map, which register it reads and why, its decisions, how it works
  around a device limit) = the package note or design, which points to the device doc
  (`(device: <file> <section>)`, or `→ doc/devices/<device>/<file>.md` in YAML) and never copies
  it. The device README lists the packages that use the unit; it never restates their decisions.
  Quirks of the software in between (an HA integration, ebusd as a program, MQTT payloads) stay in
  the note or a skill; what the device itself answers over that interface is a device fact.
- **Folder per model as installed:** `<maker>-<model>`, lowercase kebab (`vaillant-vws-83-2`).
  Several units of one model share the folder; their evidence rows name the unit. An accessory
  without its own interface or manual lives in its main unit's folder.
- **Files, evidence tags, graduation:** `.claude/rules/devices.md`, the single home of the format
  (loads when a device doc is read). **Workflow** (add a device, record a finding, answer "can X
  steer it?"): the `device-knowledge` skill. **Skeleton:** `doc/devices/_template/` (never cited).
- **Grades:** the evidence tag is the grade (rule), mapped onto `record-learning` section 2 plus
  DOC (a manufacturer document, not tested here). The record-learning gate (section 0) applies.
  An UNPROVEN fact stays in a device doc only tagged `[ASSUMED]` and only when something relies on
  it; the test that would settle it is a `plans/` step.
- **Current only:** no history narrative. A disproved fact is rewritten; the test row that
  disproved it stays as evidence. Manufacturer files under `references/` are never edited (like
  sources, but meant to be read and cited).
- **Existing device facts under a package** (`doc/heating_pv_boost/registers.md`,
  `heating-curve.md`, hardware quirks in notes) move to their device doc when that device's
  knowledge is next worked on; not rewritten for this alone.
