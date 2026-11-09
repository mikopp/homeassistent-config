# Move package notes into doc/<pkg>/

**Status:** PLAN ONLY. Awaiting explicit approval for step 1 (root CLAUDE rules 2-5).
Delete this plan in the last commit (doc/KNOWLEDGE.md#K-6).

## Context
Package notes live in `packages/notes/<pkg>.md`, while design and background for the same package live
in `doc/<pkg>/`. Goal: one folder per package under `doc/`, with the notes beside design/background.
Strategy is unchanged: the note stays lazily loaded through its own `paths:` frontmatter plus a symlink in
`.claude/rules/packages/`; only locations change. Token cost must stay identical.

## Target layout
| Today | After |
|---|---|
| `packages/notes/airflow_cooling.md` | `doc/airflow/notes.md` |
| `packages/notes/pergola.md` | `doc/pergola/notes.md` |
| `packages/notes/victron.md` | `doc/victron/notes.md` |
| `packages/notes/heating_pv_boost.md` | `doc/heating_pv_boost/notes.md` |
| `packages/notes/heating_pv_boost-registers.md` (not auto-loaded) | `doc/heating_pv_boost/registers.md` |
| `packages/notes/energy.md` | `doc/energy/notes.md` (new folder) |
| `.claude/rules/packages/<name>.md` symlinks | keep names; retarget to `../../../doc/<dir>/notes.md` |
| `<pkg>-tests.md` split rule (K-3) | `doc/<pkg>/tests.md` |

Fixed name `notes.md` mirrors `design.md` / `background.md` and avoids the airflow vs airflow_cooling
name mismatch. `packages/notes/` is removed. `packages/CLAUDE.md` stays (one-line pointer).

## Steps (each reported and approved before the next)
1. **Move**: `git mv` the 6 files; `mkdir doc/energy`; recreate the 5 symlinks with `ln -sf`
   (use `git ls-files -s` to confirm mode 120000). Frontmatter `paths:` unchanged (already repo-root-relative);
   optionally add `doc/<pkg>/notes.md` is NOT added (not needed, avoids self-trigger).
2. **Fix links** (mechanical `sed`, then review the diff):
   - Live knowledge: root `CLAUDE.md` (homes table), `packages/CLAUDE.md`, `doc/KNOWLEDGE.md` (K-1 row, K-3 header and
     `-tests` split, K-4, K-5 pointer example, K-6 new-package recipe), `.claude/skills/record-learning`,
     `.claude/skills/ha-test-harness`, `README.md:73`.
   - Notes' internal links (`heating_pv_boost` ↔ registers/victron) and `doc/*/design.md` headers.
   - YAML comments in `packages/{victron,heating_pv_boost,airflow_cooling}.yaml` (~20, comment-only).
   - `doc/*/background.md` (9 mentions): path-only fix via `sed`, not via Read (guarded).
   - Plans: `heating-compressor-cycling`, `heating-baseline-and-phase2-prerequisites`,
     `ebusd-pv-heating-optimization`, `pergola-field-calibration`, `knowledge-dedup-pergola`
     (its "created `packages/notes/pergola.md`" line), and add the new path convention to
     `knowledge-dedup-airflow` / `-energy` / `-pergola` headers so their later steps target
     `doc/<pkg>/notes.md`.
3. **Verify nothing broke**
   - `grep -rn "packages/notes"` returns nothing (except git history); all symlinks resolve (`find -L .claude/rules -xtype l` empty).
   - `.github/scripts/yaml_semantic_equal.py master packages/<each touched>.yaml` passes (comment-only).
   - `.github/scripts/ci-local.sh`; `git ls-files --eol` shows no CRLF.
   - **Loading check (K-7)** in a fresh headless session, per package: no tools → note not in context; Read
     `packages/victron.yaml` → note loaded; Read `README.md` → not loaded. Also confirm the guard
     (`Read(/doc/**/background*.md)`) does not match `notes.md`/`registers.md`.
4. **Token check**: byte-compare note files before/after (`git diff -M --stat` shows pure renames; content diff only in
   link lines) so auto-loaded size is unchanged; new link strings are not longer than before.
5. Record the convention in `doc/KNOWLEDGE.md` (no dated log), delete the repo plan file, commit, push to
   `claude/awesome-maxwell-z56vm7`. No PR unless asked; user deploys with `git pull`.

## Risks
- Symlink rules break if a target path is mistyped: caught by the `-xtype l` check and the K-7 load test.
- `energy` has no `doc/` folder yet; created with only `notes.md` (no design/background needed).
- Open branches editing `packages/notes/*` will conflict; the dedup plans (3 of them) are updated here so they
  start from the new paths.
