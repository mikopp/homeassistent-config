# Test drift check: do the in-process tests still verify what the Docker tests verified?

## Overview
PR #149 replaced 205 Docker tests (`tests/test_*.py` on master) with about 60 in-process tests
(`tests/ha`) plus 4 e2e tests. A green suite does not prove the new tests check what the old ones
checked. Seeding vs a real mosquitto is accepted and out of scope.

The branch changes no behavior in `packages/`, `custom_templates/` or `configuration.yaml` (two
comment lines in `packages/pergola.yaml`). Old and new suite test the same system, so a
differential check is possible.

Counts, master -> branch (test defs, parametrized): airflow 93 -> 11, victron 44 -> 11,
heating_pv_boost 25 -> 9, pergola 18 -> 9, shelly 10 -> 1, wallbox 7 -> 1, indicator 6 -> 1,
templates 2 -> 1.

## Design
Four checks, strongest first. The mutant script and the ledger are throwaway (scratchpad); nothing
is written to `doc/tests/background.md`. Only restored or added tests, this plan and a PR comment
are committed.

- **A. Mutation differential.** Break the YAML in a small way (a mutant); a suite that verifies the
  behavior must fail on it.
  - Generator: one change per mutant (comparison flip, threshold step, and/or, not removal,
    constant, delay/`for:`, choose branch, state string, entity id, removed action line). Keep
    mutants that still load. About 30 to 60 per package; every automation, template sensor and
    script hit at least once.
  - Run the new suite (`tests/ha`, affected module) on every mutant. For each survivor run the old
    suite (master `tests/test_<pkg>.py`, Docker) on the same mutant.
  - old kills, new survives: drift gap, restore the test. Both survive: equally blind, list only.
    New kills, old survives: improvement, ignore.
  - Pre-check: the old suite on the branch HEAD config must be green, else the baseline is invalid.
- **B. Case ledger.** Collect the 205 old ids from an `origin/master` worktree. Map each to a new
  test and asserting line, `moved to e2e`, or `dropped: <reason>`. Compare input -> expected tuples
  of parametrized tables (airflow, victron, wallbox, indicator).
- **C. Moved assertions.** Review every changed expected value, loosened tolerance, `xfail`,
  `skip`, `allow_log` and timing window in `git diff origin/master...HEAD -- tests`. Re-check
  airflow xfail (#153), `allow_log` (#155), pergola rain/user_override order, `_settle` 0.6 s,
  Victron instant-power and `delay_on` cases on the Clock.
- **D. Same claim?** Per old test, one line: same trigger path (real trigger vs
  `automation.trigger`), same observable (state vs recorded call vs seeded value), same boundary
  values. Flag any new test that reads back what it seeded.

## Steps
1. [TODO] Pre-check: old suite on branch HEAD config (Docker); collect old ids from a master worktree.
2. [TODO] Ledger (B) and assertion diff (C), review list.
3. [TODO] Mutants: new suite on all, old suite on survivors (A); airflow, victron, heating_pv_boost,
   pergola first, then the rest.
4. [TODO] Restore gaps, re-run their mutants until killed, run touched files 20x.
5. [TODO] Close: per `doc/KNOWLEDGE.md#K-6`. Report gap counts and decisions in a PR comment, record
   a confirmed method only via `record-learning`, then delete this plan.

Knowledge homes touched: none planned (`tests/ha` only); a confirmed learning goes to
`.claude/skills/ha-test-harness/SKILL.md` (K-1).

## Status
Plan written. Not started; waiting for the go-ahead for step 1.
