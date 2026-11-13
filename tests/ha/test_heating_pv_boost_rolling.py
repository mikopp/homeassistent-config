"""Rolling 30-day heating efficiency (packages/heating_pv_boost.yaml), in-process.

The six `sql` sensors sum kWh over the last 30 days from the recorder's long-term statistics; the
three template efficiencies divide those sums. Pure unit tests (owner): HA's long-term statistics
are never used.
- SQL queries: each query is taken from the package YAML (loaded, never copied), rendered through
  the sql integration's own `check_and_render_sql_query` and executed on a standalone in-memory
  SQLite with a minimal `statistics` / `statistics_meta` schema and fabricated rows. Expected
  values come from literal anchors or `_spec_sums`, a Python port of the specification.
- Efficiencies: the six sql sensors' states are seeded directly on the repo HA.
- Loading: the sql sensors set up on the repo HA (empty test recorder) without a warning → 0.

`sum` in long-term statistics is monotonic (the recorder absorbs meter resets), so the fabricated
sums are monotonic too, also for a meter that resets daily.

"Now" for a query: the real wall clock, and HA's clock is frozen to that same instant, so a query
gets the same "now" whether it reads it from Jinja (`now()`) or from SQLite (`'now'`). Window
edges keep a 120 s margin for the few milliseconds between the two.
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Mapping
from datetime import UTC, datetime
from typing import Any

import freezegun.api
import pytest
import sqlalchemy
import yaml
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.sql.util import check_and_render_sql_query
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.template import Template

from conftest import REPO, Clock, _AnyTagLoader, entity_id, seed

# ── Specification: statistic ids per sql sensor ───────────────────────────────
Y_TOTAL = "sensor.geotherm_heating_yield_total"
E_TOTAL = "sensor.technikraum_heizung_heizung_energy"
Y_SPACE = "sensor.heating_yield_by_mode_space_heating"
Y_ACTIVE = "sensor.heating_yield_by_mode_active_heating"
Y_PASSIVE = "sensor.heating_yield_by_mode_passive_heating"
E_ACTIVE = "sensor.heating_electricity_by_mode_active_heating"
E_PASSIVE = "sensor.heating_electricity_by_mode_passive_heating"
Y_WATER = "sensor.heating_yield_by_mode_water_heating"
E_WATER = "sensor.heating_electricity_by_mode_water_heating"
# Statistic ids no sensor may count (other mode buckets, a name that only extends a listed id).
UNRELATED = (
    "sensor.heating_yield_by_mode_cooling",
    "sensor.heating_electricity_by_mode_off",
    "sensor.geotherm_heating_yield_total_2",
)

SUMMED_IDS: dict[str, tuple[str, ...]] = {
    "heating_yield_30d": (Y_TOTAL,),
    "heating_electricity_30d": (E_TOTAL,),
    # Old active/passive yield ids plus the combined space-heating id: the window spans the merge.
    "space_heating_yield_30d": (Y_SPACE, Y_ACTIVE, Y_PASSIVE),
    "space_heating_electricity_30d": (E_ACTIVE, E_PASSIVE),
    "hot_water_yield_30d": (Y_WATER,),
    "hot_water_electricity_30d": (E_WATER,),
}
ALL_IDS = (*{s for ids in SUMMED_IDS.values() for s in ids}, *UNRELATED)

HOUR = 3600
DAY = 86400
WINDOW = 30 * DAY + HOUR  # cutoff = now − (30 days + 1 hour)
MARGIN = 120  # s around the cutoff (Jinja vs SQLite "now", see module docstring)

# A fabricated row: (statistic id, seconds before now, sum).
Row = tuple[str, float, float]


def _sql_queries() -> dict[str, str]:
    """unique_id → query of the package's `sql:` entries, loaded from the YAML (never copied)."""
    data = yaml.load((REPO / "packages" / "heating_pv_boost.yaml").read_text(), Loader=_AnyTagLoader)
    queries = {e["unique_id"]: e["query"] for e in data.get("sql") or []}
    missing = sorted(SUMMED_IDS.keys() - queries.keys())
    assert not missing, f"sql entries missing in packages/heating_pv_boost.yaml: {missing}"
    return {uid: queries[uid] for uid in SUMMED_IDS}


def _spec_sums(rows: list[Row]) -> dict[str, tuple[float, float]]:
    """Python port of the specification: unique_id → (kwh, days) for rows given relative to now.

    Rows inside the window (age <= WINDOW); per listed id MAX(sum) − MIN(sum), summed over the
    sensor's ids; days = age of the earliest considered row in days, 1 decimal; nothing → 0/0.
    """
    out = {}
    for uid, ids in SUMMED_IDS.items():
        inside = [(s, age, v) for s, age, v in rows if s in ids and age <= WINDOW]
        kwh = 0.0
        for s in ids:
            sums = [v for sid, _, v in inside if sid == s]
            if sums:
                kwh += max(sums) - min(sums)
        days = round(max(age for _, age, _ in inside) / DAY, 1) if inside else 0.0
        out[uid] = (kwh, days)
    return out


def _meter(stat: str, first_ago: float, last_ago: float, per_hour: float, base: float = 0.0,
           daily_reset: bool = False) -> list[Row]:
    """Hourly rows of one statistic from `first_ago` to `last_ago` seconds before now.

    `sum` grows by the hour's consumption. `daily_reset`: the underlying meter restarts at 0 every
    24 rows (a daily utility meter); the recorder's sum stays monotonic and only the hourly
    consumption varies with the hour of the day.
    """
    rows, total, age, hour = [], base, first_ago, 0
    while age >= last_ago:
        rows.append((stat, age, total))
        total += per_hour * (1 + (hour % 24) / 12) if daily_reset else per_hour
        age -= HOUR
        hour += 1
    return rows


# ── Standalone database and query execution ───────────────────────────────────
def _database(now: float, rows: list[Row], metas: tuple[str, ...]) -> sqlalchemy.Engine:
    """A fresh in-memory SQLite with the minimal schema, `metas` registered, `rows` inserted."""
    engine = sqlalchemy.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE statistics_meta (id INTEGER PRIMARY KEY, statistic_id TEXT)")
        conn.exec_driver_sql(
            "CREATE TABLE statistics (id INTEGER PRIMARY KEY, metadata_id INTEGER, start_ts REAL, sum REAL)"
        )
        meta_id = {}
        for stat in metas:
            meta_id[stat] = conn.execute(
                sqlalchemy.text("INSERT INTO statistics_meta (statistic_id) VALUES (:s)"), {"s": stat}
            ).lastrowid
        for stat, age, value in rows:
            conn.execute(
                sqlalchemy.text("INSERT INTO statistics (metadata_id, start_ts, sum) VALUES (:m, :t, :v)"),
                {"m": meta_id[stat], "t": now - age, "v": value},
            )
    return engine


def _run_queries(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, rows: list[Row], metas: tuple[str, ...] = ALL_IDS
) -> dict[str, Any]:
    """Execute every sql sensor's rendered query on a database holding `rows`.

    Returns unique_id → the single result row (a mapping), or an error string.
    """
    now = freezegun.api.real_time()
    freezer.move_to(datetime.fromtimestamp(now, UTC))
    engine = _database(now, rows, metas)
    results: dict[str, Any] = {}
    with engine.connect() as conn:
        for uid, query in _sql_queries().items():
            rendered = check_and_render_sql_query(hass, Template(query, hass))
            got = [dict(r) for r in conn.execute(sqlalchemy.text(rendered)).mappings()]
            results[uid] = got[0] if len(got) == 1 else f"{len(got)} result rows: {got}"
    engine.dispose()
    return results


def _compare(results: Mapping[str, Any], expect: Mapping[str, tuple[float, float]], where: str) -> list[str]:
    """One message per sensor whose (kwh, days) differs from `expect`; kwh/days never NULL."""
    failures = []
    for uid, (kwh, days) in expect.items():
        row = results[uid]
        if not isinstance(row, dict):
            failures.append(f"{where}: {uid}: {row}")
            continue
        got_kwh, got_days = row.get("kwh"), row.get("days")
        if got_kwh is None or abs(float(got_kwh) - kwh) > 1e-6 * max(1.0, abs(kwh)):
            failures.append(f"{where}: {uid} kwh = {got_kwh!r}, want {kwh}")
        if got_days is None or abs(float(got_days) - days) > 1e-9:
            failures.append(f"{where}: {uid} days = {got_days!r}, want {days}")
    return failures


# ── Window cases ──────────────────────────────────────────────────────────────
# Distinct hourly increments per id: a sum shows exactly which ids were counted.
_INC = {Y_TOTAL: 1000.0, E_TOTAL: 250.0, Y_SPACE: 64.0, Y_ACTIVE: 16.0, Y_PASSIVE: 4.0,
        E_ACTIVE: 8.0, E_PASSIVE: 2.0, Y_WATER: 32.0, E_WATER: 1.0}
_UNRELATED_INC = 4096.0


def _edge_rows() -> list[Row]:
    """Per id: a row just older than the cutoff, one just inside, one an hour ago.

    The old row's sum is 500 below the inside one: counting it would add 500 per id.
    """
    rows: list[Row] = []
    for stat in ALL_IDS:
        inc = _INC.get(stat, _UNRELATED_INC)
        rows += [(stat, WINDOW + MARGIN, 0.0), (stat, WINDOW - MARGIN, 500.0), (stat, HOUR, 500.0 + inc)]
    return rows


# 30 days + 1 h − 120 s → 30.04 days → 30.0.
_EDGE_DAYS = round((WINDOW - MARGIN) / DAY, 1)


def _partial_rows() -> list[Row]:
    """12 days of hourly history (daily-resetting meters included); unrelated ids 25 days back."""
    rows: list[Row] = []
    for i, stat in enumerate(sorted(_INC)):
        rows += _meter(stat, 12 * DAY, HOUR, 0.25 * (i + 1), base=1000.0 * i, daily_reset=i % 2 == 0)
    for stat in UNRELATED:
        rows += _meter(stat, 25 * DAY, HOUR, 7.0)
    return rows


def _merge_rows() -> list[Row]:
    """Old active/passive yield ids until 10 days ago, then the combined space-heating id."""
    rows = _meter(Y_ACTIVE, 29 * DAY, 10 * DAY, 1.5, base=300.0)
    rows += _meter(Y_PASSIVE, 29 * DAY, 10 * DAY, 0.5, base=40.0)
    rows += _meter(Y_SPACE, 10 * DAY, HOUR, 2.0, daily_reset=True)
    # Their sums stay flat after the merge (orphaned statistics keep their last sum).
    rows += [(Y_ACTIVE, 5 * DAY, max(v for s, _, v in rows if s == Y_ACTIVE)),
             (Y_PASSIVE, 5 * DAY, max(v for s, _, v in rows if s == Y_PASSIVE))]
    return rows


WINDOW_CASES: list[tuple[str, list[Row], tuple[str, ...], dict[str, tuple[float, float]]]] = [
    # (name, rows, registered statistic ids, expected unique_id → (kwh, days))
    ("empty_database", [], (), {uid: (0.0, 0.0) for uid in SUMMED_IDS}),
    ("registered_ids_without_rows", [], ALL_IDS, {uid: (0.0, 0.0) for uid in SUMMED_IDS}),
    ("only_rows_older_than_the_cutoff",
     [(s, WINDOW + MARGIN + h * HOUR, 10.0 - h) for s in ALL_IDS for h in range(5)], ALL_IDS,
     {uid: (0.0, 0.0) for uid in SUMMED_IDS}),
    ("cutoff_edge_and_id_selection", _edge_rows(), ALL_IDS, {
        "heating_yield_30d": (1000.0, _EDGE_DAYS),
        "heating_electricity_30d": (250.0, _EDGE_DAYS),
        "space_heating_yield_30d": (64.0 + 16.0 + 4.0, _EDGE_DAYS),
        "space_heating_electricity_30d": (8.0 + 2.0, _EDGE_DAYS),
        "hot_water_yield_30d": (32.0, _EDGE_DAYS),
        "hot_water_electricity_30d": (1.0, _EDGE_DAYS),
    }),
    ("partial_history_12_days", _partial_rows(), ALL_IDS, _spec_sums(_partial_rows())),
    ("old_and_new_space_heating_ids_added", _merge_rows(), ALL_IDS, _spec_sums(_merge_rows())),
]


async def test_sql_window_sums(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Each sql query, run on fabricated statistics, sums the 30-day window as specified."""
    # Anchors of the port-derived cases, so a broken port cannot pass them vacuously.
    partial = _spec_sums(_partial_rows())
    assert all(days == 12.0 for _, days in partial.values()), partial
    merge = _spec_sums(_merge_rows())["space_heating_yield_30d"]
    active = 1.5 * (19 * 24)
    passive = 0.5 * (19 * 24)
    space = sum(2.0 * (1 + (h % 24) / 12) for h in range(10 * 24 - 1))
    assert abs(merge[0] - (active + passive + space)) < 1e-6 and merge[1] == 29.0, merge

    failures = []
    for name, rows, metas, expect in WINDOW_CASES:
        failures += _compare(_run_queries(hass, freezer, rows, metas), expect, name)
    assert not failures, "\n".join(failures)


def test_sql_queries_avoid_the_entity_id_keyword() -> None:
    """No query names `entity_id` (the sql integration rejects that on the recorder database)."""
    offenders = [uid for uid, q in _sql_queries().items() if "entity_id" in q.lower()]
    assert not offenders, f"queries containing entity_id: {offenders}"


# ── The sql sensors on the repo HA ────────────────────────────────────────────
class _SqlLogs(logging.Handler):
    """Collects WARNING+ records of the sql integration (a NULL result only warns)."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.hits: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.hits.append(f"{record.levelname} {record.name}: {record.getMessage()}")


@pytest.fixture
def sql_logs() -> Generator[_SqlLogs]:
    """Attach `_SqlLogs` to the sql integration's logger; request it BEFORE `ha` to see the boot."""
    handler = _SqlLogs()
    logger = logging.getLogger("homeassistant.components.sql")
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


async def test_sql_sensors_load_clean(sql_logs: _SqlLogs, ha: HomeAssistant) -> None:
    """The six sql sensors exist, read 0 kWh / 0 days from the empty test recorder, log nothing."""
    failures = []
    for uid in SUMMED_IDS:
        eid = entity_id(ha, "sensor", "sql", uid)
        state = ha.states.get(eid)
        if state is None:
            failures.append(f"{uid} ({eid}): no state")
            continue
        attrs = state.attributes
        if attrs.get("unit_of_measurement") != "kWh":
            failures.append(f"{uid}: unit {attrs.get('unit_of_measurement')!r}, want 'kWh'")
        # The state is the `kwh` column (every result column is also an attribute).
        if "kwh" not in attrs or state.state != str(attrs["kwh"]):
            failures.append(f"{uid}: state {state.state!r} is not the kwh column {attrs.get('kwh')!r}")
        if state.state in ("unknown", "unavailable") or float(state.state) != 0:
            failures.append(f"{uid}: state {state.state!r}, want 0")
        if attrs.get("days") is None or float(attrs["days"]) != 0:
            failures.append(f"{uid}: days {attrs.get('days')!r}, want 0")
    issues = [i for (domain, i) in ir.async_get(ha).issues if domain == "sql"]
    if issues:
        failures.append(f"sql repair issues: {issues}")
    if sql_logs.hits:
        failures.append("sql log records:\n" + "\n".join(sql_logs.hits))
    assert not failures, "\n".join(failures)


# ── Efficiency templates ──────────────────────────────────────────────────────
EFFICIENCIES = {  # template unique_id → (entity id, yield sql uid, electricity sql uid)
    "heating_efficiency_30d": ("sensor.heating_efficiency_30d", "heating_yield_30d", "heating_electricity_30d"),
    "space_heating_efficiency_30d": (
        "sensor.space_heating_efficiency_30d", "space_heating_yield_30d", "space_heating_electricity_30d"),
    "hot_water_efficiency_30d": (
        "sensor.hot_water_efficiency_30d", "hot_water_yield_30d", "hot_water_electricity_30d"),
}
UNKNOWN, UNAVAILABLE = "unknown", "unavailable"

# Reset vector before each case: every efficiency 2.5.
_RESET = {uid: ("50" if "yield" in uid else "20") for uid in SUMMED_IDS}

# (name, sql inputs over the reset vector, expected template uid → number or state string)
EFFICIENCY_CASES: list[tuple[str, dict[str, str], dict[str, float | str]]] = [
    ("each_efficiency_reads_its_own_pair",
     {"heating_yield_30d": "40", "heating_electricity_30d": "10",
      "space_heating_yield_30d": "30", "space_heating_electricity_30d": "12",
      "hot_water_yield_30d": "33", "hot_water_electricity_30d": "11"},
     {"heating_efficiency_30d": 4.0, "space_heating_efficiency_30d": 2.5, "hot_water_efficiency_30d": 3.0}),
    ("rounded_to_two_decimals",
     {"heating_yield_30d": "100", "heating_electricity_30d": "30",
      "space_heating_yield_30d": "200", "space_heating_electricity_30d": "30",
      "hot_water_yield_30d": "125", "hot_water_electricity_30d": "45.5"},
     {"heating_efficiency_30d": 3.33, "space_heating_efficiency_30d": 6.67, "hot_water_efficiency_30d": 2.75}),
    ("floor_boundary_9_99_is_unknown",
     {"heating_electricity_30d": "9.99", "space_heating_electricity_30d": "9.99",
      "hot_water_electricity_30d": "9.99"},
     {uid: UNKNOWN for uid in EFFICIENCIES}),
    ("floor_boundary_10_is_a_number",
     {"heating_electricity_30d": "10.0", "space_heating_electricity_30d": "10.0",
      "hot_water_electricity_30d": "10.0"},
     {uid: 5.0 for uid in EFFICIENCIES}),
    ("no_electricity_is_unknown_not_zero",
     {"heating_electricity_30d": "0", "space_heating_electricity_30d": "0", "hot_water_electricity_30d": "0"},
     {uid: UNKNOWN for uid in EFFICIENCIES}),
    ("no_yield_above_the_floor_is_zero",
     {"heating_yield_30d": "0", "space_heating_yield_30d": "0", "hot_water_yield_30d": "0"},
     {uid: 0.0 for uid in EFFICIENCIES}),
    ("yield_unavailable",
     {"heating_yield_30d": UNAVAILABLE, "space_heating_yield_30d": UNAVAILABLE,
      "hot_water_yield_30d": UNAVAILABLE},
     {uid: UNAVAILABLE for uid in EFFICIENCIES}),
    ("electricity_unavailable",
     {"heating_electricity_30d": UNAVAILABLE, "space_heating_electricity_30d": UNAVAILABLE,
      "hot_water_electricity_30d": UNAVAILABLE},
     {uid: UNAVAILABLE for uid in EFFICIENCIES}),
    ("only_one_pair_unavailable",
     {"space_heating_electricity_30d": UNAVAILABLE},
     {"heating_efficiency_30d": 2.5, "space_heating_efficiency_30d": UNAVAILABLE,
      "hot_water_efficiency_30d": 2.5}),
]


def _matches(state: str | None, want: float | str) -> bool:
    """A state string equals `want`: the exact string, or the number (2 decimals)."""
    if state is None:
        return False
    if isinstance(want, str):
        return state == want
    try:
        return abs(float(state) - want) < 1e-9
    except ValueError:
        return False


def _efficiency_ids(hass: HomeAssistant) -> dict[str, str]:
    """Template uid → entity id (looked up; must be the specified id)."""
    ids = {uid: entity_id(hass, "sensor", "template", uid) for uid in EFFICIENCIES}
    wrong = {uid: eid for uid, eid in ids.items() if eid != EFFICIENCIES[uid][0]}
    assert not wrong, f"efficiency entity ids differ from the specification: {wrong}"
    return ids


async def _seed_sql(hass: HomeAssistant, values: Mapping[str, str]) -> None:
    """Seed the sql sensors (by unique_id) with kWh states."""
    await seed(hass, {entity_id(hass, "sensor", "sql", uid): (v, {"unit_of_measurement": "kWh"})
                      for uid, v in values.items()})


async def test_efficiency_30d_table(ha: HomeAssistant, clock: Clock) -> None:
    """Efficiency = yield ÷ electricity (2 decimals); under 10 kWh electricity `unknown`; a missing
    input `unavailable`. The frozen clock keeps the sql sensors from polling over the seeds.
    """
    eff = _efficiency_ids(ha)
    failures = []
    for name, inputs, expect in EFFICIENCY_CASES:
        await _seed_sql(ha, _RESET)
        if bad := {u: ha.states.get(e).state for u, e in eff.items() if not _matches(ha.states.get(e).state, 2.5)}:
            failures.append(f"{name}: reset not reached: {bad}")
            continue
        await _seed_sql(ha, inputs)
        for uid, want in expect.items():
            got = ha.states.get(eff[uid])
            if not _matches(got and got.state, want):
                failures.append(f"{name}: {uid} = {got and got.state!r}, want {want!r}")
    assert not failures, "\n".join(failures)


async def test_window_ratio_is_the_ratio_of_sums(
    ha: HomeAssistant, clock: Clock, freezer: FrozenDateTimeFactory
) -> None:
    """Day A 2 kWh heat / 1 kWh electricity, day B 30 / 10: the sql sums are 32 / 11 and the
    efficiency is 32 / 11 = 2.91, not the mean of the daily ratios (2 + 3) / 2 = 2.5.
    """
    rows: list[Row] = [
        (Y_TOTAL, 2 * DAY, 100.0), (Y_TOTAL, DAY, 102.0), (Y_TOTAL, HOUR, 132.0),
        (E_TOTAL, 2 * DAY, 50.0), (E_TOTAL, DAY, 51.0), (E_TOTAL, HOUR, 61.0),
    ]
    results = _run_queries(ha, freezer, rows)
    failures = _compare(results, {"heating_yield_30d": (32.0, 2.0), "heating_electricity_30d": (11.0, 2.0)},
                        "sql sums")
    assert not failures, "\n".join(failures)
    await _seed_sql(ha, {**_RESET, "heating_yield_30d": str(results["heating_yield_30d"]["kwh"]),
                         "heating_electricity_30d": str(results["heating_electricity_30d"]["kwh"])})
    got = ha.states.get(_efficiency_ids(ha)["heating_efficiency_30d"]).state
    assert _matches(got, 2.91), f"heating_efficiency_30d = {got!r}, want 2.91 (32 / 11; mean of daily ratios 2.5)"
