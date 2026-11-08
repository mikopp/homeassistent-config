# Knowledge conventions

How knowledge about this repo is stored for humans and agents. Section IDs (`K-1` …) are stable:
link them as `doc/KNOWLEDGE.md#K-6`, never renumber, mark retired IDs as gone.

## K-1 Where knowledge lives

| Home | What goes there | How it loads | Limit |
|---|---|---|---|
| root `CLAUDE.md` | rules needed in every session (constraints, version gate, MCP, config layout, this table) | always, at session start | < 100 lines |
| `.claude/rules/*.md` | cross-package rules tied to file types (`ha-yaml.md`, `tests.md`) | lazily, when a file matching its `paths:` is read | ~4 KB |
| `packages/notes/<pkg>.md` | current facts of one package (see K-3) | lazily: the note has its own `paths:` frontmatter and is symlinked as `.claude/rules/packages/<pkg>.md` | ≤ 24 KB |
| `.claude/skills/<topic>/` | cross-package topic knowledge (templates, MQTT, energy, test harness) and workflows (`record-learning`) | on demand, when the task matches the skill description | one topic per skill |
| `doc/<pkg>/design.md` | current architecture, decision tables, derivation results (see K-4) | on demand (read when needed) | ≤ 40k chars |
| `doc/<pkg>/background.md`, `doc/sources/<pkg>/` | history, superseded designs, investigations; raw transcripts, spreadsheets | guarded, read only when the user asks for history | none |
| YAML comments | what a block does + one-line why + pointer (see K-5) | with the file | short |
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

## K-3 Note template (`packages/notes/<pkg>.md`)

Frontmatter `paths:` lists the package YAML, its tests, and `doc/<pkg>/design.md` if one exists.
Never list background or sources. Sections, in order:

1. Header: scope, rule paths, design-doc link
2. Invariants
3. Hardware / integration quirks
4. Entity map (IDs from `default_entity_id` or ha-mcp lookup, never from `unique_id`)
5. Decisions in force (one-line why; no background link)
6. Known biases / open issues
7. Tests: package-specific test facts only (generic harness knowledge is in the `ha-test-harness`
   skill). Above ~2 KB, split into `packages/notes/<pkg>-tests.md` with its own symlink rule and
   `paths:` only `tests/test_<pkg>.py`.
8. Related

Size: ≤ 24 KB (~6k tokens). Over that, move derivations to `design.md` and stories to background.

## K-4 Design docs (`doc/<pkg>/design.md`)

- Needed when the package has a state machine, a decision table, derived math, or more than ~800
  YAML lines. Otherwise the note is enough.
- ≤ 40k chars. Holds current results; the derivation story goes to `background.md`.
- Stable, short, grep-able heading IDs (`PG-4`, `AF-7.2`, `VIC-N3`; background uses `<PKG>-B<n>`).
  Never renumber; mark retired IDs as gone.
- Never `@`-import it. Add `doc/<pkg>/design.md` to the note's `paths:` so editing the design doc
  loads the note.

## K-5 YAML comment style

- Each comment says **what** the block does, at most **one line of why**, and a pointer for more:
  `# → doc/<pkg>/design.md#PG-4` or `# → packages/notes/<pkg>.md`.
- No dates, no stories, no "was changed because": that is git history or background.
- The automation `description:` is the human summary shown in the HA UI; keep it current.
- Jinja `{# #}` comments are template text: treat changes to them as code changes.

## K-6 How to extend

- **New package:** create `packages/notes/<pkg>.md` with `paths:` frontmatter (K-3), then
  `ln -s ../../../packages/notes/<pkg>.md .claude/rules/packages/<pkg>.md` and commit the symlink.
- **Complex package** (K-4 threshold): add `doc/<pkg>/design.md` and put it in the note's `paths:`.
- **New cross-package topic:** a skill in `.claude/skills/<topic>/SKILL.md`; the first words of its
  description carry the trigger.
- **One home per fact.** Every other place points to it; never copy.
- **Every plan's last step:** distil the result into note / design / skill, move the story to
  background, update pointers, check the note is ≤ 24 KB, then DELETE the plan.
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
headless in this repo 2026-11-07 (K-7 method).

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
