# CI / test-suite speedups and hang diagnosis

**Status:** IMPLEMENTED on `ci/test-speedups`; awaiting its first CI run against current `master`
(HA pin 2026.10.1). Everything below was developed on the `fix-victron-ac-dc-mixup` branch
(PR #101) while debugging that feature's CI, then split out so it can merge independently.
**Target files:** `.github/workflows/ha_check.yaml`, `.github/workflows/requirements.txt`,
`pyproject.toml`, `tests/conftest.py`, `tests/test_airflow.py`, `.claude/learnings.md`, `CLAUDE.MD`
**Not in this change:** any `packages/*.yaml`, `tests/test_victron.py`, `tests/test_pergola.py`
(see "Scope boundary").

Evidence grades follow `.claude/learnings.md`: **CONFIRMED** (stack trace / source read /
deterministic reproduction), **OBSERVED** (real data, alternative explanation open),
**UNPROVEN** (hypothesis).

---

## 1. What changes, and why

| # | Change | File | Purpose | Grade |
|---|---|---|---|---|
| 1 | Default `timeout=30` onto the harness's `requests.get/post/delete/...` | `tests/conftest.py` | Harness v0.11.0 calls `requests` with no `timeout=`; a container that accepts TCP and never answers blocks the process forever. `assert_entity_state(timeout=)` does not help — its deadline is checked *between* polls, each poll calls the unbounded `get_state()`. | CONFIRMED (thread dump: `socket.recv_into` inside `requests.get`) |
| 2 | `pytest-timeout`, `--timeout=90 --timeout-method=thread` | `requirements.txt`, `ha_check.yaml` | Turn a silent hang into a failure that dumps every thread's stack. 90 s ≈ 4× the slowest legitimately passing test observed (21.8 s). | CONFIRMED (it named the blocking line on first use) |
| 3 | `timeout_func_only = true` | `pyproject.toml` | Without it the timeout charges session-fixture setup (`docker compose up`, 60–90 s) to whichever test triggers it. | CONFIRMED (thread dump: `docker_manager.py:603 → subprocess.run`) |
| 4 | Job-level `timeout-minutes: 20` | `ha_check.yaml` | Bounds fixture-setup hangs that (3) deliberately no longer catches; default is 6 h. | design choice |
| 5 | `test_pergola.py` as its own pytest invocation | `ha_check.yaml` | Its sun fixtures call `jump_to_next(month="Jun")` repeatedly (a full year each time once June 21 has passed). Own process ⇒ own container and clock. Gives a deterministic per-file clock. **Not** a hang fix (see §3). | CONFIRMED mechanism; NOT the hang cause |
| 6 | `jump_to_next(hour=10, …)` → `fast_forward(timedelta(minutes=11))` | `tests/test_airflow.py` (`_assert_recomputes_after_reload`) | `jump_to_next` is forward-only: re-requesting an already-passed hour silently advances a full day. Neither sensor under test reads `schedule.*`, `workday` or any time function, so no absolute anchor is needed — only crossing the 10-min `delay_on/delay_off` window. | CONFIRMED (`time_machine.py` read; template bodies read) |
| 7 | Background prefetch of the HA + AppDaemon images, barrier before first consumer; drops `actions/cache` + `docker save/load` | `ha_check.yaml` | `docker load` of the gzipped cache was a steady 61 s, single-threaded, on the critical path. | OBSERVED (timings, below) |
| 8 | Retag the pinned image as `homeassistant/home-assistant:stable` | `ha_check.yaml` | The harness's bundled compose file hardcodes that name; without the tag it pulls a second, *unpinned* image — slower, and the suite then tests a different HA than `check_config`. | OBSERVED (73.2 s → 21.0 s from "collected" to first PASSED); the correctness half is by construction |
| 9 | Pin read from `.github/ha-versions/ha/Dockerfile` | `ha_check.yaml` | Master's (#116) Dependabot-tracked source of truth. Combined with (7); exported via `$GITHUB_ENV` because the config-check step uses `"$HA_IMAGE"`. | — |

### Documentation changes riding along
`CLAUDE.MD` (HA version gate pointing at the Dockerfile pin, persistent-memory rule, "never write an
unconfirmed learning") and `.claude/learnings.md` (graded learnings). Both came out of the
debugging below; the learnings file also holds general HA lessons (integration platform, entity
registry reclaim) that were learned on the Victron work — they reference
`packages/victron.yaml` / `plans/victron-ac-referenced-accounting.md`, which land in the feature PR.

---

## 2. Measured effect

All numbers are from this branch's real CI runs (no local runs possible — no Docker).

| What | Before | After |
|---|---|---|
| Whole job, green | 4 m 12 s – 4 m 42 s | 3 m 27 s (run 32992976830) |
| HA image acquisition | 61 s (`docker load`, every run) | 41 s barrier incl. 2.35 GB image + AppDaemon pull (run 38145739645; mostly *not* hidden behind other steps — only ~8 s of cover exists) |
| Harness start → first PASSED | 73.2 s (pulls a second image) | 21.0 s (image already local) |
| Mocked-clock travel in the airflow reload helper | +2 days per call (2 × `jump_to_next`) | +22 min (2 × `fast_forward(11 min)`) |

The image-acquisition win is "a registry pull beats a single-threaded gunzip", not overlap. Do not
read it as more.

---

## 3. What was disproved on the way (so it is not re-litigated)

1. **"Pergola year-jumps cause the hang."** A docs-only commit (byte-identical test code) hung
   anyway, with pergola already isolated. The isolation is kept for determinism, not as a fix.
2. **"The clock drifts a decade."** Only pergola had year-scale jumps; the remainder drifted ~2 weeks.
3. **"HA's trigger engine drops custom attributes"** — never positively demonstrated; the feature
   uses state-only baseline sensors regardless (see the feature plan).
4. **"Dropping the `jump_to_next` alignment call causes a hang"** — reproduced *with* the call in
   place. Entry deleted from learnings.

The one confirmed hang mechanism is (1) in the table: an unbounded `requests` call. *Why the HA
container stops answering is still unknown* — the test side is merely bounded.

---

## 4. Will this be green on `master`? — analysis

CI could not be run locally; this is a read-through of what the change touches.

**Behavioural surface (only these tests see new behaviour):**
- Every test: HTTP calls now raise `ReadTimeout` after 30 s instead of blocking. A previously
  *passing* run cannot be affected unless a single call legitimately took >30 s.
- Every test: per-test 90 s function budget. Slowest observed passing test: 21.8 s.
- `test_airflow.py`: the two tests that use `_assert_recomputes_after_reload`
  (`test_flush_needed_recomputes_after_reload_unknown`,
  `test_low_needed_recomputes_after_reload_unknown`) now advance 2 × 11 min rather
  than 2 days. Same sensors, same 10-min delay window; no template reads a wall-clock hour.
- `test_pergola.py`: unchanged file, new process. Its fixtures behave as before; airflow
  automations no longer share its event loop (the reason the old "pergola first" sort existed).

**Known fragility, deliberately NOT redesigned here (documented in `test_airflow.py`):**
two airflow tests (`test_flush_unavailable_when_dependency_missing`,
`test_heat_ventilation_low_needed_off_when_outdoor_below_indoor`) get their clock crossing from the
helper above running earlier *by nodeid order*, not from anything of their own. Removing the
helper's first `fast_forward`, renaming a test, or running one with `-k` makes them fail with
`current: 'unknown'`. If CI shows exactly that, the fix is an explicit
`fast_forward(timedelta(minutes=11))` in the failing test, not reverting this change.

**Things this change cannot prove and CI must:**
1. Master moved to HA **2026.10.1** (#116); this was developed against 2026.8.x. Config-check and
   the delayed-sensor behaviour are the two places a version bump could surface.
2. #114/#118 changed `packages/airflow_cooling.yaml` (drying boost, startup waits) after the
   airflow clock work was written. The new drying tests set `binary_sensor.airflow_humidity_drying_needed`
   directly, so they do not use the delayed sensors — but that is a read-through, not a run.
3. The retag step assumes the harness keeps `image: homeassistant/home-assistant:stable`. The
   pinned harness commit is in `requirements.txt`; a Dependabot bump of it should re-check this.

**Green criteria for the first CI run:** config check passes; pergola step and "rest" step both
pass; no `Timeout` thread dumps; job < ~5 min.

---

## 5. Scope boundary with the Victron feature PR

`tests/test_victron.py` also contains many `jump_to_next(hour=10, …)` → `fast_forward` conversions
(20 jumps ⇒ ~11 days of mocked travel ⇒ every `platform: integration` step integrating 86 400 s).
Those are part of the wholesale rewrite of that file for the feature and **ship with the feature
PR**, not here: this PR must not touch `test_victron.py`, or the two PRs would conflict on it.
Likewise `tests/conftest.py` carries two disjoint groups of hunks — the HTTP shim / sort comment
(here) and the Victron entity seeds (feature PR) — which merge cleanly in either order.

**Merge order:** this PR first. The feature PR is functionally independent but its tests are the
ones that exposed the hangs; without the shim and timeouts it can stall CI instead of failing.

## Status
- [x] HTTP timeout shim (`tests/conftest.py`)
- [x] `pytest-timeout` + `timeout_func_only` + job timeout
- [x] Pergola isolated pytest invocation, summary / PR-comment / fail steps updated
- [x] Airflow reload helper: `fast_forward` instead of day-scale jumps; ordering dependencies documented
- [x] Image prefetch, barrier, retag; Dockerfile pin consumed
- [x] Dangling plan references repointed to this file
- [ ] First CI run on `master` base, read honestly
