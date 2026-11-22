# Knowledge conventions

How knowledge about this repo is stored for humans and agents. Section IDs (`K-1` …) are stable:
link them as `doc/KNOWLEDGE.md#K-6`, never renumber, mark retired IDs as gone.

## K-1 Where knowledge lives

Every knowledge file is one of four **kinds**; the kind decides when it loads and how it is written:
- **always**: root `CLAUDE.md` and each skill's `name` + `description`. Paid in every session and
  every subagent.
- **rule**: a `.claude/rules/**/*.md` with `paths:` frontmatter (file-type rules; package notes and
  `tests.md`, symlinked into `.claude/rules/packages/`). Loads when a matching file is read or
  edited (K-8). Imperative and short.
- **skill**: the body of `.claude/skills/<topic>/SKILL.md`. Loads when the task matches the
  description. Workflows and cross-package know-how, one topic per skill.
- **reference**: every other file an agent reads (design docs, device docs, package reference docs
  (`doc/<pkg>/<topic>.md`), skill `references/*.md`, plans, this file). Never loads by itself: it is
  reached only through a pointer that says when to read it (K-1.3).

Not loaded as knowledge: background and sources (guarded), manufacturer copies under
`doc/devices/*/references/`, issues, git.

| Home | Kind | What goes there |
|---|---|---|
| root `CLAUDE.md` | always | rules needed in every session (constraints, version gate, MCP, config layout, homes table) |
| `.claude/rules/*.md` | rule | file-type rules: `ha-yaml.md`, `tests.md`, `plans.md` (plan format), `devices.md` (device-doc format), `knowledge.md` (sends here) |
| `doc/<pkg>/notes.md`, `doc/<pkg>/tests.md` | rule (symlink) | what an agent must know before editing the package (K-1.1, K-3) |
| `.claude/skills/<topic>/SKILL.md` | skill | cross-package topic knowledge and workflows (`record-learning`, `device-knowledge`) |
| `.claude/skills/<topic>/references/*.md` | reference | a skill's detail, indexed in its `SKILL.md` (K-1.3) |
| `doc/<pkg>/design.md` | reference | current architecture: components, decision tables, interfaces, decisions and trade-offs, known gaps, extension points (K-1.1, K-4) |
| `doc/<pkg>/<topic>.md` | reference | lookup material the package owns (unit facts: K-9), indexed in the note header |
| `doc/devices/<device>/` | reference | one physical unit and how it is reached, independent of the packages using it (K-9); `devices.md` loads when one is read |
| `plans/` | reference | open work and hypotheses only; deleted when done; large ones split (`.claude/rules/plans.md`) |
| YAML comments | with the file | what a block does + one-line why + pointer (K-1.1, K-5) |
| `doc/<pkg>/background.md`, `doc/<topic>/background.md`, `doc/sources/<pkg>/` | guarded | history, superseded designs, investigations; raw transcripts, spreadsheets. Never current behaviour; read only when the user asks for history |
| GitHub issues | external | confirmed bug or flaky test not being fixed now; `#n` linked from the affected note; a plan only when work starts |
| git history / PRs | external | the log: what changed when and why |

Rules:
- **Never use `@` imports in a rule.** They are expanded eagerly at launch, so the imported file is
  always paid for (CONFIRMED, K-8). The symlink layout loads lazily.
- **Agent knowledge never refers to background or sources.** No knowledge file, YAML comment or
  test points to them (a pointer invites the read the guard prevents): state the needed fact where
  needed. Exempt (they name background as a destination): this file, root `CLAUDE.md`, the
  `record-learning` routing table, `.claude/settings.json`, plans. Guard: `permissions.ask` on Read
  and `cat` of `doc/**/background*.md`, `doc/sources/**` (Grep passes, K-8); the layout check warns
  on any other mention.
- No dated logs anywhere (`evidence.md` T rows are evidence, not logs: K-9). Git and PRs are the log.

### K-1.1 Note, YAML comment or design doc?

One home per kind of fact. Ask the question of each home in order; the first "yes" is the home.

| Home | One-question test | Holds |
|---|---|---|
| device doc | Would it stay true if HA were replaced or another package used the unit? | what the hardware is, does, answers and refuses; how it is reached (K-9) |
| YAML comment | Is it about this one block only? | what the block does, at most one line of why, a pointer (K-5) |
| note | Must an agent know it **before editing** this package's YAML or tests? | invariants (one line each), what the package does about hardware/integration quirks, entity map, decisions in force with a one-line why, owner-supplied values and their origin, open issues (`#n`) (K-3) |
| design doc | Is it needed to **change the architecture**, or to check that an addition does not break it? | components and responsibilities, state machines and decision tables, interfaces/contracts, decisions with rejected alternatives and trade-offs, known gaps, extension points and what breaks them (K-4) |

- **Note vs YAML comment: never both.** A fact local to one block lives in its comment. A fact
  spanning blocks or invisible in the YAML (hardware quirk, cross-block invariant, reason for an
  owner value) lives in the note; the blocks point to it (`→ doc/<pkg>/notes.md`).
- **Note vs design doc.** The note auto-loads, the design doc does not. For anything that fails
  silently when broken, the note keeps the one-line imperative plus `→ design.md#ID`; the design
  doc holds mechanism, table and trade-off, not that line. A decision's why: one line in the note,
  or chosen/rejected/trade-off in the design doc with the note pointing to it; never both in full.
- **Design doc vs implementation.** A design doc may repeat a note fact it needs to stand alone
  (the conclusion, not the evidence), never implementation detail. Test: *would the sentence need
  editing if an entity were renamed, a helper retuned, or a template restructured without changing
  behaviour?* Yes = implementation: point to it.

  | Architecture (design doc) | Implementation detail (note, device doc or YAML; the design doc points) |
  |---|---|
  | which component decides and which single writer owns each actuator | entity ids, entity maps, helper lists, automation `id`s |
  | the state set, the transitions and the priority order, with why that order | trigger lists, condition-by-condition template text, `float()` defaults |
  | the formula's shape, the derived constant and why it matters | config values and thresholds as such (a helper's tuned number) |
  | contract with another package: what is read/published, unit, sign, availability | register decodes, payload formats, MQTT topics |
  | invariant and the mechanism that keeps it | per-block behaviour already commented in the YAML |
  | how to verify a change (identities that must hold) | test lists, restated test cases |

  Refer to a component by its role. Never an entity id (registry state, derived from device, area
  and name: `.claude/rules/ha-yaml.md`) and never a list or map of entities: name a concept, an
  entity by its name, or the source attribute (ebusd register, Somfy property, Venus OS path). A
  number appears only when the design depends on it (derived constant, test oracle). Point, never copy:
  `(note: Entity map)`, `(note: <section>)`, `(YAML: <automation alias or sensor name>)`,
  `(test: <test name>)`, `→ doc/<pkg>/design.md#ID` between design docs.

  Existing design docs are not rewritten for this alone; whoever edits one replaces entity ids
  and lists in the part they touch.

### K-1.2 Size caps

Characters, never lines; hard (error) / warn; `SIZE_CAPS` in the layout check (K-8) holds the
numbers and a why per row. Not capped: `_template`, background, sources, `doc/devices/*/references/`.
- always: root `CLAUDE.md` 8,000/7,000; skill `description:` 500/400
- rule 5,000/4,000; note 24,000/21,600; `tests.md` 8,000/6,000
- skill: `SKILL.md` body 20,000/12,000 (and > 500 lines); `references/*.md` and other skill files
  40,000/30,000
- reference: design doc 40,000/24,000 (and a section > 3,000); package reference doc
  40,000/30,000; `doc/KNOWLEDGE.md` 30,000/26,000; `plans/*.md` 40,000/25,000; device (one
  decision per read): `README.md` 8,000/6,000; `evidence*.md` 16,000/12,000; other 12,000/10,000

At a cap, move or split; never raise it:
- note, in this order: unit facts (incl. access, registers) → device doc; mechanisms → design
  (K-4.1); test facts → `tests.md`. Cut dated values, stories, hypotheses. Never cut an
  invariant: move it, leave a pointer.
- rule: how-to → a skill. `SKILL.md`: detail → `references/*.md`.
- device: split into the standard parts (`.claude/rules/devices.md` Parts): `behaviour.md` per
  subsystem into `<topic>.md` (it keeps States summary, `## Control`, `## Does not work`);
  `interface.md` into `access-<path>.md` and `registers-<area>.md` (it keeps the access summary
  and `## Unusable on this unit`); `evidence.md`: rows no fact cites → `evidence-archive.md`,
  never delete a row or reuse a T number.
- any other reference: split per K-1.3. A plan first collapses finished steps and distils
  confirmed facts; still over the warn level → a master plan with sub-plans
  (`.claude/rules/plans.md`).

### K-1.3 Splitting a reference: progressive disclosure

An agent loads the smallest file that answers the decision in front of it.
- **Pointer with a condition.** Every reference is reached through a pointer `<file> — read
  before/when <decision or task>`, placed in a file the agent already has loaded when that decision
  comes up (note header, rule, `SKILL.md`, an index). Never "read first" or "always read": that
  turns a reference into an always-cost.
- **Split by decision, not by size.** Each part answers one kind of question (one circuit's
  registers, one subsystem, one workflow), is readable without its siblings, and starts with one
  line: what it covers and which file indexes it.
- **The parent becomes the index:** one line per part with its condition, plus what all parts
  share. Index per kind: `SKILL.md` for `references/*.md`; for device parts the README file map
  (`behaviour.md` for a subsystem, `interface.md` for access and register parts); the note header
  for `doc/<pkg>/<topic>.md`; the master plan for sub-plans. Design docs are not split into files: K-4 (cut, or split sections).
- Point straight to the part when the condition already decides it; to the index only when the
  choice needs reading.
- A line repeated across parts is allowed only when it saves a read; a contradiction never is
  (K-6 copy rule).
- The layout check fails a part that no index names (K-8).

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

1. Header: scope, rule paths, design-doc link (`<PKG>-*` IDs), each package reference doc with its
   read-when condition (K-1.3); per unit driven a `Device:` line, e.g. `Device: doc/devices/<d>/ —
   read behaviour.md before changing a write to the unit; interface.md before adding a register.`
2. Invariants: one line each; when a design ID holds the mechanism, end with `→ design.md#ID`
   and do not restate it (K-1.1)
3. Hardware / integration quirks (graded; a design doc cites them, never copies them). A fact
   about the unit or how it is reached lives in its device doc, a generic program or platform
   fact in a skill (K-9); the note keeps what this package must do about it, one line ending
   `(device <ID>)` (K-6 copy rule)
4. Entity map (IDs from `default_entity_id` or ha-mcp lookup, never from `unique_id`); the full
   map lives here, never in the design doc
5. Decisions in force (one-line why; no background link)
6. Known biases / open issues (`#n`; the design doc's Known gaps lists the architectural ones by
   `#n`, the note keeps the entry and its grade)
7. Tests: package-specific test facts only (generic harness knowledge is in the `ha-test-harness`
   skill). Above ~2,000 chars, split into `doc/<pkg>/tests.md` with its own symlink rule and
   `paths:` only `tests/ha/test_<pkg>.py` (plus the `tests/e2e/` files that cover the package, if any).
8. Related

Size: K-1.2 (caps; what to move at a cap).

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
  hardware quirks and measured values (the device doc or the note: cite `(device <ID>)` or
  `(note: <section>)`, use the conclusion);
  cross-package topic facts (a skill); another package's note or design (point to it);
  procedures (resets, deploy steps: a skill or the PR).
- **Device facts:** a design cites the unit's behaviour by anchor `(device <ID>)` and uses only
  the conclusion; never its evidence, tags, decode or numbers unless the design derives from them.
  Each decision or invariant that depends on unit behaviour ends with `Rests on: (device <ID>)[, …]`.
  It may rest on an `[ASSUMED]` fact only under Known gaps (graded UNPROVEN, with a `plans/` step
  or `#n`). When a fact it rests on changes or is disproved, the agent changing the device doc (it
  found the design hit by the grep) must not change the architecture itself: it either confirms the
  decision still holds (and adjusts the one-line why), or adds the decision to Known gaps with a
  new issue `#n` and tells the owner. Re-architecting is a plan.
- **Grades:** a statement about this repo's config needs none (the YAML wins: fix the doc).
  Anything else (HA/upstream semantics, expected physical results) carries a grade
  (`record-learning` section 2), preferably by citing the note or skill holding it. Owner-chosen
  rationale: `(owner decision)`. An UNPROVEN claim stays in `plans/` unless the design works around
  it; then under Known gaps, graded UNPROVEN.
- **IDs:** stable, short, grep-able heading IDs `<PKG>-<n>[.<m>]` (`PG-4`, `AF-7.2`; background
  uses `<PKG>-B<n>`); one prefix per design doc. Never renumber; a new topic takes the next free
  number. Before retiring an ID, grep `packages/ custom_templates/ tests/ dashboards/ doc/
  .claude/` and repoint every hit, then list it on one final line: `Retired: <ID> → <ID>`.
- **Size:** K-1.2 (on-demand files are truncated above 40,000 chars, K-8). No section over
  ~3,000 chars: split it or cut.
- **Loading:** never `@`-import it; list it in the note's `paths:` so editing it loads the note.
- **Template** (sections in this order; omit an empty one):
  1. Header: scope (package files), "YAML wins: fix this doc", link to the note. No status line.
  2. Purpose and boundaries: goals, out of scope, neighbour packages.
  3. Components and data flow: responsibilities, the single writer per output; a diagram only if
     it pays for itself (roles, not an entity list).
  4. State machine / decision table(s) in force.
  5. Formulas and derived constants (results only).
  6. Invariants: mechanism and why it holds (the rule line stays in the note).
  7. Interfaces: inputs consumed, outputs published, contract (sign, unit, availability).
  8. Decisions and trade-offs: chosen / rejected / cost accepted; `Rests on:` per decision.
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

Lives in `.claude/rules/comments.md`, a rule that auto-loads when YAML or Jinja is edited, so
writing a comment never needs this file.

## K-6 How to extend

- **New package:** `doc/<topic>/notes.md` with `paths:` (K-3), then commit
  `ln -s ../../../doc/<topic>/notes.md .claude/rules/packages/<pkg>.md` (`<pkg>` = YAML name:
  `airflow_cooling.md` -> `doc/airflow/notes.md`).
- **Complex package** (K-4 threshold): add `doc/<pkg>/design.md` from the K-4 template and put
  it in the note's `paths:`.
- **New device:** `device-knowledge` skill (copies `doc/devices/_template/`, K-9).
- **New cross-package topic:** a skill in `.claude/skills/<topic>/SKILL.md`; the first words of its
  description carry the trigger.
- **One home per fact.** Every other place points to it. Exception, for token efficiency only: an
  auto-loaded note may keep a one-line copy of a device fact (the conclusion, no evidence) so a
  routine edit needs no device read; the copy ends with its source anchor `(device <ID>)`. A copy
  never adds to or qualifies its source. Contradiction between a copy and its source is a bug: the
  device doc wins until the owner decides.
- **Every plan's last step (Close):** distil the result into note / design (K-4.1 gate) / device
  doc (T rows, `device-knowledge` skill) / skill, move the story to `doc/<pkg|topic>/background.md`,
  update pointers, check sizes (K-1.2), then DELETE the plan. The layout check fails a plan without
  a Close step.
- Moving a fact: confirm the target holds it before deleting; never promote an UNPROVEN claim.

## K-7 Verifying a loading change

Rules load at session start, so test in a FRESH headless session from the repo root:
`claude -p "<prompt>" --model haiku --allowedTools Read --max-turns 4`, asking about a distinctive
sentence of the rule (not its file name: `CLAUDE.md` names files). Per changed rule or note:
1. no tools: content NOT in context; 2. read a matching file: content in context, source named;
3. read a non-matching file (`README.md`): content NOT in context.

Skills: a task prompt matching the description without naming the skill
(`--allowedTools Read,Skill,Grep,Glob`) must invoke it and answer from its body; one outside the
description must not.

## K-8 Loading mechanics (Claude Code)

What the layout in K-1 relies on. Grades: DOC = Claude Code docs (2026-11-07), CONFIRMED = tested
headless in this repo 2026-11-07 (K-7 method), OBSERVED as in `record-learning` section 2.

- Startup loads only root `CLAUDE.md` and each skill's name + description; a skill body loads
  when the skill is invoked. (CONFIRMED)
- A `paths:` rule loads when Read/Write/Edit (or a single-file `cat`/`head`) touches a matching
  file. **Grep and Glob do not trigger it**: before relying on package facts after a search, read
  the package YAML or its note. (DOC; Read trigger CONFIRMED)
- Broken frontmatter makes a rule load always. (DOC)
- On-demand files (path rules, nested `CLAUDE.md`, their imports) are truncated above 40,000
  chars. (DOC)
- `@` imports in a rule load eagerly at launch; a symlinked note with its own `paths:` loads
  lazily. (CONFIRMED, canary)
- Path rules also load inside subagents (a general-purpose subagent reading `packages/energy.yaml`
  got the energy note and `ha-yaml.md`). (CONFIRMED)
- Guards: `permissions.ask` blocks Read and `cat`, not Grep. (CONFIRMED)
- Rules are context, not enforcement: what must never happen (CRLF, YAML errors) needs a check
  (`.gitattributes`, `ci-local.sh`, CI).
- `.github/scripts/check_knowledge_layout.py` (`ci-local.sh`, workflow `knowledge-layout.yml`)
  enforces this layout; the full list is its docstring. Not yet checked: K-4 template sections.
- Word a findings trigger by the concrete case ("measured value, hardware quirk, user-supplied
  reason": 3/3), not the category ("bug or non-obvious fact": 1/3, haiku). (OBSERVED)

## K-9 Device knowledge (`doc/devices/<device>/`)

What a physical unit is, does and answers, independent of which package uses it: identity,
references (manuals by document number and page, catalogs, software docs), behaviour, how it can
and **cannot** be steered (first-class, never dropped silently), how it is reached (access path,
registers) and the tests behind each fact. Any hardware (heat pump, ventilation, Somfy, Victron).

- **One home per fact** (K-1.1 first row). True of the unit whatever package uses it = device
  doc, including how it is reached: access path (bus, gateway, the program or HA integration in
  between and its config source), addressing, polling limits, write semantics and the wiring a
  write needs, register definitions, and quirks of the software in between as they affect this
  unit. How a package uses the unit (entity map, which register it reads and why, its decisions,
  workarounds) = the package note or design, which points to the device doc (`(device <ID>)`, or
  `→ doc/devices/<device>/<file>.md` in YAML) and copies only per K-6 (anchored one-liner).
  Generic program or HA-platform behaviour = its docs, cited by a `software` References row
  (`Covers`), never restated; undocumented and used by several devices or packages = a skill
  (`ha-mqtt`). The README lists the packages, never their decisions.
- **No entity ids in a device doc:** they are registry state and change on a rename; the note's
  entity map maps entity → register, the device doc defines the register.
- **Folder per model as installed:** `<maker>-<model>`, lowercase kebab (`vaillant-vws-83-2`).
  Several units of one model share the folder; their evidence rows name the unit. An accessory
  without its own interface or manual lives in its main unit's folder.
- **Files, evidence tags, fact IDs, graduation:** `.claude/rules/devices.md`, the single home of the format
  (loads when a device doc is read). **Workflow** (add a device, record a finding, answer "can X
  steer it?"): the `device-knowledge` skill. **Skeleton:** `doc/devices/_template/` (never cited).
- **Worth writing (gate, `device-knowledge` skill):** a device doc holds only what saves a later
  agent from a miss, a misreading or a costly read: a source it would not check, one that is
  ambiguous or easy to misread, or one too long to re-read. Never a copy of what a reference
  answers plainly; for an access path only what the program's documentation omits, gets wrong or
  hides for this unit. Skipping names what would be lost; a doubtful case goes to the owner.
- **Minimal device:** `README.md` alone (identity, References with per-topic page pointers, Used
  by) when no fact passes the gate and every reference is stable and agent-readable (HTML, MD,
  text; a text-layer PDF with page pointers). It becomes a full doc with its first gated fact.
- **Grades:** the evidence tag is the grade (rule), mapped onto `record-learning` section 2
  (DOC = a manufacturer or `software` doc). The record-learning gate (section 0) applies.
  An UNPROVEN fact stays in a device doc only tagged `[ASSUMED]` and only when something relies on
  it; the test that would settle it is a `plans/` step.
- **Current only:** no history narrative. A disproved fact is rewritten; the test row that
  disproved it stays as evidence. Manufacturer files under `references/` are never edited (like
  sources, but meant to be read and cited).
- **Existing device facts under a package** (decodes, access facts, hardware quirks in notes) move
  to the device doc when that device is next worked on, not for this alone.
