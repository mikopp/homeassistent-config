# Home Assistant Config — Claude Instructions

## Important constraints for this project:
1. ALWAYS create/maintain a feature specific implementation plan file in the `plans` folder. 
2. NEVER start implementation without explicit approval
3. ALWAYS await step-by-step instructions and explicit approval before coding
4. ALWAYS update the plan file's status section after each step
5. ALWAYS summarize what was done before asking for next steps
6. ALWAYS write comments that describe each part of the implementation in the source code file.
7. User will deploy via `git pull` on the HA host, NEVER do that yourself
8. ALL files use LF (Linux) line endings — never CRLF. Before committing run `git ls-files --eol`
   (nothing may show `w/crlf` or `i/crlf`). Enforced by `.gitattributes` (`eol=lf`) and `.editorconfig`.

Deploy/migration docs come from `git diff origin/master...HEAD`, never the live system.

## Local CI checks
Run `.github/scripts/ci-local.sh` before pushing. It creates `.venv`, installs the CI Python deps and runs
the Docker-free checks (YAML style fixer, yamllint, resolved-config lint, template extraction). Needs
`brew install yamllint python@3.15`. `check_config` and pytest need Docker and only run in CI.

## HA version gate — check before trusting any info
The pinned HA version lives in the `FROM` line of `.github/ha-versions/ha/Dockerfile` (an image tag
like `ghcr.io/home-assistant/home-assistant:2026.10.1`; Dependabot bumps it). `.HA_VERSION` was
removed in #116 and must not be read. CI config check and the test harness both use this image. Before applying
ANY information from internet search, official HA docs, ha-mcp results, or even this repo's own
existing code/comments — check it's still accurate for that major version. HA changes fast: config
keys get renamed/removed, integrations get rewritten, YAML syntax shifts across major versions.

- Read the `FROM` line of `.github/ha-versions/ha/Dockerfile` first, at the start of any research into
  HA behavior/config/docs. The live instance may differ from the pin; check it with ha-mcp
  (`ha_get_system_health`, `homeassistant.info.version`) when that matters.
- Verify behaviour against source at the pinned tag: `gh api repos/home-assistant/core/contents/<path>?ref=<tag>`.
  Docs were ambiguous or silent every time it mattered; reading the source is what turns a guess
  into a CONFIRMED fact.
- When citing docs or web results, prefer version-pinned docs (e.g. `www.home-assistant.io/docs`
  reflects latest — verify against changelog/release notes if the feature is old or obscure) over
  version-less blog posts/forum answers, which may predate or postdate this install by years.
- If a found answer's version isn't stated, say so explicitly and flag it as unverified for this
  major version rather than presenting it as fact.
- Existing YAML in this repo reflects the version it was written under — don't assume patterns here
  are still current best practice without checking; note conflicts instead of silently "fixing" them.

## MCP usage (read-only)
The ha-mcp connection is available for DISCOVERY ONLY:
- Look up entity IDs, device names, areas, and current states
- Understand what integrations and devices exist
- Verify entity IDs before using them in automations

**Never call any ha-mcp tool that writes, changes state, or calls a service.**
Only use read tools: entity lookup, area listing, device listing, state queries.

## Config structure
This repo IS the Home Assistant config directory. All automations, scripts, blueprints, and helpers
are defined here in YAML files — not in the HA UI or via MCP tools.

### Global files (keep lean — no feature-specific content)
- `configuration.yaml` — loads packages, includes automations/scripts/scenes, global integrations only
- `automations.yaml` — only automations that span multiple features or have no natural feature home
- `scripts.yaml` — same principle as automations.yaml
- `blueprints/automation/mine/` — custom automation blueprints
- `custom_templates/` — Jinja macros imported by templates (`{% from 'x.jinja' import ... %}`);
  currently only `airflow_decision.jinja`, the airflow package's single decision

### Feature packages (`packages/<feature>.yaml`)
Each feature gets its own file under `packages/`. A package file may contain any combination of:
`input_boolean`, `input_number`, `input_text`, `input_select`, `input_datetime`,
`template`, `automation`, `script`, `sensor`, `binary_sensor`, etc.

HA merges all package keys into the global config automatically via:
```yaml
homeassistant:
  packages: !include_dir_named packages
```

**Rule:** When adding anything for a named feature (e.g. pergola, irrigation, alarm),
create or edit `packages/<feature>.yaml`. Do NOT add it to configuration.yaml or
the global automations/scripts files.

HA YAML rules (helpers, template sensors, MQTT entity ids, device key) live in `.claude/rules/ha-yaml.md` and load automatically when a matching file is touched. Rules and package notes load only on Read/Edit of a matching file, not on Grep/Glob: after searching, read the YAML or note before relying on package facts.

## Learnings — hard rule
**Never write an unconfirmed learning** (one green CI run or "symptom went away" is not proof).
Hypotheses go to the feature's `plans/` file, marked as such.
To record anything learned, invoke the `record-learning` skill: it holds the evidence rules and routing.

## Where knowledge lives
Details, limits and how to extend: `doc/KNOWLEDGE.md`.

| Home | Holds |
|---|---|
| `packages/notes/<pkg>.md` | current facts of one package; auto-loads when its files are touched (symlinked rule) |
| `.claude/rules/*.md` | file-type rules (`ha-yaml.md`, `tests.md`); auto-load on matching paths |
| `.claude/skills/<topic>/` | cross-package topic knowledge and workflows (`record-learning`) |
| `doc/<pkg>/design.md` | current architecture/derivations of complex packages; read on demand |
| `doc/<pkg>/background.md`, `doc/sources/<pkg>/` | history and raw material: not design-relevant, never cite as current behaviour |
| YAML comments | what + one-line why + pointer to note/design |
| `plans/` | open work and hypotheses only; deleted when done |
| GitHub issues | confirmed bugs/flaky tests not fixed now; link `#n` from the note; plan only when work starts |
| git history / PRs | the log; no dated logs elsewhere |
