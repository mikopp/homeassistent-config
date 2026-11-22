# `tests/e2e` (real container)

Part of the `ha-test-harness` skill; grades as there (CONFIRMED unless marked).

- ONE session container (`docker run --network host`, image from the Dockerfile `FROM`), a host mosquitto, own client
  `ha_client.py` with a timeout on every call and deadline polling, no fixed sleeps.
- Bootstrap boot (onboarding, MQTT and workday through the real config flows, production-like entity ids), then a clean
  restart: only the log after it is judged (a fresh HA logs ERROR on `homeassistant: start` MQTT publishes before the
  MQTT entry exists). It fails on ERROR+, deprecations, tracebacks, and WARNING from `custom_components.*`. `test_zz_log_hygiene.py` runs last; its `EXTERNAL_NOISE` (environment) and `KNOWN_CONFIG_BUGS`
  (issue numbers) lists are explicit: add an entry only with its cause.
- A restore test must make the value final before the restart (e.g. an integral fed absurd power, then 0 W), else the
  sum keeps moving afterwards and the assertion is weak; `wait_stable` for a value that settles after a burst.
- `.github/scripts/install_custom_components.py` is the one installer of `climate_template` (CI, `ci-local.sh`, `stage.py`).
