# climate_template deprecation warnings on HA 2026.11

**Status:** OPEN. Nothing to implement in this repo; waits for the owner and for the upstream component.

## Overview
The custom component `climate_template` (upstream litinoveweedle/hass-template-climate, `ref` 0.8.2, staged from
`tests/custom_components.yaml` into `custom_components/` for the tests) logs deprecation warnings
on HA 2026.11.1 (still at upstream 0.8.2, CONFIRMED in-process; observed in the in-process layer; the e2e layer runs the same component in the
real container, the CI container log shows the same messages; the e2e tolerance was mutation-checked against it). HA says the old behaviour "stops working in Home Assistant 2027.11":
- `homeassistant.helpers.frame`: the component reads/writes `_attr_temperature_unit`,
  `_attr_current_temperature`, `_attr_target_temperature(_low|_high)`; HA wants the `_attr_native_*`
  names.
- `custom_components.climate_template.climate`: `TemplateClimate provides the deprecated
  target_temperature(_high|_low)`, use `native_target_temperature*`.

The test guards (`log_guard` / `_KNOWN_CONFIG_LOGS` in `tests/ha/conftest.py`, `EXTERNAL_NOISE` in
`tests/e2e/test_zz_log_hygiene.py`) fail on any deprecation and on any WARNING from the component's
own logger, so both layers carry a narrow, named tolerance for exactly these two message shapes. Everything else it or any other
integration logs still fails.

## Steps
1. [TODO] Owner: open (or find) the upstream issue in litinoveweedle/hass-template-climate (this
   session can neither read nor open issues there) and put its number in the tolerance comments.
2. [TODO] When hass-template-climate moves to `_attr_native_*` / `native_target_temperature*`:
   bump `ref` in `tests/custom_components.yaml`, delete the tolerance entries (two in each layer)
   and run the full `ci-local.sh` (and e2e).
3. [TODO] Close: per `doc/KNOWLEDGE.md#K-6`; delete this plan once the tolerances are gone.

## Hypotheses (UNPROVEN)
- HYPOTHESIS: HA 2027.11 removes the old attribute handling, after which the component's
  climate entities misbehave on a live system. Only HA's own message says so; not tested.
- HYPOTHESIS: the live HA host (not this repo) shows the same warnings in its log once it runs 2026.11.

## Knowledge homes
Tolerance comments in the two test files only; no note change until confirmed behaviour exists.
