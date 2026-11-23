# Plan: `loxone` package and a dedicated Loxone heartbeat

## Status
- [x] Research and plan written (awaiting owner approval + answers to the open questions)
- [ ] Step 1 Refactor: move all Loxone MQTT sensors to `packages/loxone.yaml` (no behaviour change)
- [ ] Step 2 Heartbeat sensor + `Loxone Online` from heartbeat age
- [ ] Step 3 Warm enough gated by the heartbeat (replaces `expire_after`)
- [ ] Step 4 Consumers, recorder, dashboard
- [ ] Step 5 Tests
- [ ] Step 6 Docs + deploy note
- [ ] Step 7 Close

## Overview
Today "is Loxone alive" is implicit: `binary_sensor.loxone_heating_heating_loxone_warm_enough`
has `expire_after: 86400`, and `binary_sensor.heating_loxone_online` is just
`has_value(warm_enough)`. Two problems with that:
- liveness piggybacks on a comfort signal;
- `expire_after` measures *message arrival* in HA, so a stale **retained** message delivered after
  an HA restart counts as fresh for another 24 h.

New: Loxone publishes a dedicated heartbeat, **retained**, carrying a timestamp. HA computes
liveness from the *content* (timestamp age), so a stale retained value is recognised at once.
At the same time, all Loxone MQTT sensors move into one package.

Pinned HA: `2026.11.1` (`.github/ha-versions/ha/Dockerfile`).

## Open questions (owner)
1. **Timestamp epoch.** "Loxone Unix Timestamp timer object format": is it
   (a) Loxone time, seconds since **2009-01-01 00:00:00 UTC** (Unix = value + 1230768000), or
   (b) a real Unix timestamp (seconds since 1970)? A sample payload settles it.
   HYPOTHESIS: some Miniserver functions output 2009-epoch values based on *local* time, not
   UTC. You say it is UTC; Step 2 checks it against a live payload (an hour off would show up as
   a timestamp in the future/past by 3600/7200 s).
2. **Topic and cadence.** Proposed topic `loxone/heartbeat`. How often does Loxone send it? This
   matters only for the dashboard, since the 24 h threshold stays as today.
3. **Payload.** Plain integer (for example `562000000`), or with decimals or text?
4. **Loxone Online entity id.** Recommended: a new `binary_sensor.loxone_online` (unique_id
   `loxone_online`) in the loxone package; the old `binary_sensor.heating_loxone_online`
   disappears, losing its short history. Alternative: keep the old unique_id/entity id (history
   kept, but the name keeps a misleading `heating_`).

## Design
### Package `packages/loxone.yaml` (new; all Loxone MQTT inputs)
| Entity | Source | Notes |
|---|---|---|
| Washer / Tumble Dryer / Dishwasher Power + Energy (6) | moved unchanged from `energy.yaml` | same `unique_id` → same entities, statistics and Energy Dashboard untouched (moving a block between package files is not a platform change) |
| `binary_sensor.loxone_heating_heating_loxone_warm_enough` (MQTT, raw) | moved from `heating_pv_boost.yaml` | `expire_after` **removed**; becomes the raw input only |
| `sensor.loxone_heartbeat` (MQTT, new) | `loxone/heartbeat` | `device_class: timestamp`; converts the payload to an aware UTC datetime; empty or non-numeric payload → keep the last value (`ha-mqtt` skill) |
| `binary_sensor.loxone_online` (template, new) | heartbeat age | `connectivity`; on while `now() - heartbeat < 24 h`; `now()` re-renders every minute, so it goes off by itself at most ~1 min late |
| `binary_sensor.loxone_warm_enough` (template, new) | raw warm enough | same state as raw; `availability: is_state('binary_sensor.loxone_online','on')` → **unavailable when the heartbeat is older than 24 h**, as today |

Shared Loxone device(s): the heartbeat sits on a new `loxone_miniserver` device; warm enough
keeps its `loxone_heating` device (identifiers unchanged).

Why a template gate instead of MQTT `availability:`: MQTT availability is re-evaluated only when
a message arrives, so time passing (heartbeat ageing) would never flip it. A template with `now()` is
re-rendered every minute.

### Behaviour vs today
- Consumers' contract is unchanged: warm enough `on` → `off` wanted; `off`/unavailable/unknown → heat.
- Difference 1: Loxone silent but warm_enough not re-sent → today it expires 24 h after the last
  warm_enough message; new: 24 h after the last *heartbeat timestamp*.
- Difference 2: after an HA restart with a stale retained heartbeat (>24 h), warm enough is
  unavailable immediately (today: trusted for another 24 h).
- Difference 3: the hourly re-send of warm_enough no longer matters to HA (harmless if kept).
- Heartbeat timestamp in the future (clock skew): age is negative → counts as online. No upper
  bound; flagged as a known gap rather than adding a rule nobody asked for.

### Design-doc impact
`doc/heating_pv_boost/design.md` HPB-1 (control-law table, column "Loxone `warm_enough`") names
the input; only the entity reference/source changes, the rows do not. No invariant changes.

## Steps
### Step 1 Refactor (no behaviour change) [TODO]
- Create `packages/loxone.yaml` (K-5 header and block comments); move the 6 appliance meters
  and the raw warm_enough sensor, ids unchanged.
- Remove them from `energy.yaml` / `heating_pv_boost.yaml`; fix both headers.
- Check: `ci-local.sh --package loxone`, `--package energy`, `--package heating_pv_boost`. Tests
  should pass unchanged (they look up entities by unique_id or entity id, not by file).

### Step 2 Heartbeat + online [TODO]
- Depends on open questions 1-3. Verify `as_datetime(<number>)` / `utcfromtimestamp`-style
  conversion returns an aware UTC datetime at tag 2026.11.1 (source: `helpers/template`).
- Add `sensor.loxone_heartbeat` and `binary_sensor.loxone_online`; delete
  `binary_sensor.heating_loxone_online` from `heating_pv_boost.yaml` (or keep its ids, per Q4).

### Step 3 Gate warm enough [TODO]
- Add the template `binary_sensor.loxone_warm_enough` with availability on `loxone_online`.
- Raw MQTT warm enough: drop `expire_after`; comment says "raw input, read the gated one".

### Step 4 Consumers [TODO]
- `heating_pv_boost.yaml`: `sensor.heating_wanted_operating_mode`, `sensor.heating_control_state`
  → read `binary_sensor.loxone_warm_enough`; recorder include list: add heartbeat, online, gated
  warm enough (keep the raw for comparison).
- `dashboards/heating-dashboard.yaml`, `README.md`: entity references.
- `.claude/skills/ha-mqtt/SKILL.md`: re-check its warm_enough/expire_after example; adjust only if it
  becomes wrong (pointer, not a new learning).

### Step 5 Tests [TODO]
- `tests/ha/test_energy_loxone.py` → `test_loxone.py` (package-named): meters unchanged + heartbeat
  payload → timestamp table (valid, empty, junk).
- `tests/ha/test_heating_pv_boost_comfort.py::test_loxone_silent_24h_counts_as_not_warm_enough` →
  heartbeat-based: fresh heartbeat + warm → `off`; move the clock past 24 h with no new heartbeat →
  warm enough unavailable, online off → `on`; new heartbeat → `off` again. Plus: a retained heartbeat
  already older than 24 h at start → unavailable immediately. The "identical payload restarts
  expiry" case goes away.
- `tests/ha/test_energy_expire_after.py`, `tests/baseline.py`, `conftest.py` helpers: update the
  references; the comfort tests must publish a fresh heartbeat in their setup.
- Read the `ha-test-harness` skill first (frozen clock moves).
- Full `.github/scripts/ci-local.sh` before push.

### Step 6 Docs + deploy [TODO]
- New `doc/loxone/notes.md` (K-3 template, `paths:` frontmatter) + symlink
  `.claude/rules/packages/loxone.md`; move the "Loxone appliance sensors: no `expire_after`"
  section from `doc/energy/notes.md`; heartbeat topic, epoch and format, 24 h gate.
- `doc/heating_pv_boost/notes.md` "Owner-side configuration" and control-law text: point to the
  gated sensor and the loxone note.
- Deploy note from `git diff origin/master...HEAD`: Loxone must publish the heartbeat **before**
  `git pull` + restart, otherwise warm enough is unavailable → comfort heats (safe direction). The old
  `binary_sensor.heating_loxone_online` becomes orphaned (remove it in the UI), per Q4.

### Step 7 Close [TODO]
- Close: per `doc/KNOWLEDGE.md#K-6`: confirmed facts (epoch/UTC check against a live payload)
  via `record-learning`; HPB design-doc entity reference updated; delete this plan.

## Knowledge homes touched
`doc/loxone/notes.md` (new) + symlink, `doc/energy/notes.md`, `doc/heating_pv_boost/notes.md`,
`doc/heating_pv_boost/design.md` (entity reference only), `doc/heating_pv_boost/tests.md` if it
names the test, YAML comments.
