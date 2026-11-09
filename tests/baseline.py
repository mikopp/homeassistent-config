"""Baseline of the test suites: known-good helper values and the states of entities that do not
exist in a test HA (MQTT devices, Somfy, ComfoConnect, weather station, ...).

Pure data, no imports, so BOTH layers use the same baseline (plans/test-execution.md, Step 2):
- the Docker-harness suite (tests/conftest.py: `baseline_inputs`, `baseline_states`) applies it
  over REST before every test;
- the in-process layer (tests/ha/conftest.py: `seed`, `apply_baseline`) applies it with
  `hass.states.async_set` and real helper actions.

Order matters (dicts and lists keep it): helpers first, then the states, in the order below.
"""

# ── Helper actions (applied first, in this order) ─────────────────────────────────────────
# (domain, action, data) for the helpers that are not input_number values.
BASELINE_ACTIONS: list[tuple[str, str, dict]] = [
    ("input_boolean", "turn_on", {"entity_id": "input_boolean.pergola_automatic_enabled"}),
    # The indicator→pergola_heating sync automation is disabled by default so the baseline
    # indicator seed ("neutral" = heating season) cannot flip pergola_heating behind the tests.
    # Its own tests turn it on explicitly.
    ("automation", "turn_off", {"entity_id": "automation.pergola_sync_heating_from_indicator"}),
    ("input_boolean", "turn_off", {"entity_id": "input_boolean.pergola_heating"}),
    ("input_boolean", "turn_on", {"entity_id": "input_boolean.pergola_cooling_optimized"}),
    ("input_boolean", "turn_off", {"entity_id": "input_boolean.airflow_cooling_automatic_enabled"}),
    ("input_boolean", "turn_off", {"entity_id": "input_boolean.heating_pv_boost_enabled"}),
    ("input_select", "select_option", {
        "entity_id": "input_select.pergola_automation_state",
        "option": "sun_automatik_cooling",
    }),
]

# ── input_number values (applied after BASELINE_ACTIONS, with input_number.set_value) ───────
BASELINE_NUMBERS: dict[str, float] = {
    "input_number.pergola_pv_conversion_factor": 3.2,
    "input_number.pergola_shading_sensitivity": 0.9,
    "input_number.pergola_min_sun_elevation": 10,
    "input_number.pergola_deadband_angle": 5,
    "input_number.pergola_rain_recovery_step": 0,
    "input_number.pergola_last_set_slat_angle": 0,
    "input_number.airflow_cooling_target_temperature": 21.5,
    "input_number.airflow_min_dew_diff": 2.0,
    "input_number.airflow_min_temp_diff": 1.5,
    "input_number.airflow_target_humidity": 55,
    "input_number.airflow_min_humidity": 45,
    "input_number.airflow_max_humidity": 55,
    "input_number.pergola_max_tilt_angle": 122,
    "input_number.pergola_wall_azimuth": 204,
    "input_number.pergola_slat_width": 22,
    "input_number.pergola_slat_pivot_spacing": 20,
    "input_number.pergola_slat_thickness": 3,
    "input_number.airflow_bypass_efficiency_max": 0.818,
    "input_number.airflow_bypass_efficiency_min": 0.05,
    "input_number.heating_boost_offset": 1.5,
    "input_number.heating_pv_surplus_threshold": 1500,
    "input_number.heating_pv_deficit_threshold": 500,
    "input_number.heating_pv_min_battery_soc": 70,
    "input_number.heating_return_temp_max": 30,
    # Production values for the indicator thresholds (heating below / passive cooling
    # above / active cooling above).
    "input_number.heating_indicator_heating_below": 12,
    "input_number.heating_indicator_passive_cooling_above": 16,
    "input_number.heating_indicator_active_cooling_above": 20,
}

# ── States (applied last, in this order) ──────────────────────────────────────────────────
# entity_id: (state, attributes). Mostly entities a test HA does not have; a few computed
# sensors are pinned to a known value too (see the comments).
# Attribute sets shared by many entries below.
_ATTRS_W = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
_ATTRS_KWH = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
BASELINE_STATES: dict[str, tuple[str, dict]] = {
    # Sun — seeded to midday above_horizon; may be overwritten by the sun integration
    # within seconds if the fake time is set to night. Tests that need a specific sun
    # position use the midday_sun fixture which uses the time machine.
    "sun.sun": ("above_horizon", {"elevation": 45, "azimuth": 180}),
    # Victron solar charger (MQTT — broker absent in CI). Raw DC input — the repointed
    # sensor.solar_yield_watts (AC-referenced, packages/victron.yaml) is computed from
    # sensor.victron_dc_pv_total_power instead, not from this one.
    "sensor.victron_solar_yield_dc_watts": ("1500", {"unit_of_measurement": "W", "device_class": "power"}),
    # Victron MQTT sensors — all power sensors at 0 W so template sensors start
    # at 0 and energy accumulators do not advance during unrelated tests.
    # Multi DC power is a template of battery voltage × Multi DC current (packages/victron.yaml);
    # 50 V × 0 A = 0 W keeps η at its 100 % bootstrap in every test.
    "sensor.victron_battery_voltage": ("50", {"unit_of_measurement": "V", "device_class": "voltage", "state_class": "measurement"}),
    "sensor.victron_vebus_dc_current": ("0", {"unit_of_measurement": "A", "device_class": "current", "state_class": "measurement"}),
    "sensor.victron_dc_pv_total_power": ("0", _ATTRS_W),
    "sensor.victron_grid_l1_power": ("0", _ATTRS_W),
    "sensor.victron_grid_l2_power": ("0", _ATTRS_W),
    "sensor.victron_grid_l3_power": ("0", _ATTRS_W),
    "sensor.victron_ac_load_l1": ("0", _ATTRS_W),
    "sensor.victron_ac_load_l2": ("0", _ATTRS_W),
    "sensor.victron_ac_load_l3": ("0", _ATTRS_W),
    "sensor.victron_ac_inverter_power": ("0", _ATTRS_W),
    "sensor.victron_battery_soc": ("50", {"unit_of_measurement": "%", "device_class": "battery", "state_class": "measurement"}),
    # Raw DC lifetime counter — feeds the repointed sensor.victron_solar_yield_total_kwh
    # (AC-referenced) via counter-delta, and the battery energy residual's mppt_src.
    "sensor.victron_solar_yield_dc_total_kwh": ("0.0", {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}),
    "sensor.victron_ac_inverter_energy_total_kwh": ("0.0", {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}),
    # VEBus/MultiPlus conversion-efficiency accumulators (trigger template sensors,
    # packages/victron.yaml). Seeded to 0.0 so sensor.victron_multiplus_conversion_efficiency
    # is deterministically at its 100 % bootstrap in every test that does not explicitly
    # exercise eta — without this, minute ticks from unrelated tests would slowly accumulate
    # into it.
    "sensor.victron_multiplus_ac_out_energy": ("0.0", _ATTRS_KWH),
    "sensor.victron_multiplus_dc_in_energy": ("0.0", _ATTRS_KWH),
    "sensor.victron_multiplus_conversion_loss_energy": ("0.0", _ATTRS_KWH),
    # sensor.victron_solar_yield_total_kwh is now the REPOINTED AC-referenced accumulator
    # (see packages/victron.yaml's repoint note) — same reset pattern as the other trigger
    # accumulators above.
    "sensor.victron_solar_yield_total_kwh": ("0.0", _ATTRS_KWH),
    # Counter-delta baselines (victron.yaml, own dedicated state-only sensors — not custom
    # attributes, see that file's comment) reset to literal 'unknown' so every test starts
    # un-baselined, same semantics the -1 sentinel used to get from an empty attribute.
    "sensor.victron_solar_yield_dc_baseline_kwh": ("unknown", {}),
    "sensor.victron_ac_pv_energy_baseline_kwh": ("unknown", {}),
    # go-e Charger wallbox (MQTT auto-discovery — broker absent in CI). These are
    # the SOURCE entities behind sensor.wallbox_power / sensor.wallbox_energy.
    # Seeded in the go-e API v2 native units (nrg[11] in W, eto in Wh) so the
    # wrappers' unit normalisation is exercised on the conversion path.
    "sensor.go_echarger_homekopp_power_total": ("0", {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}),
    "sensor.go_echarger_homekopp_total_energy_charged": ("3500", {"unit_of_measurement": "Wh", "device_class": "energy"}),
    # Weather station (UDP integration — absent in CI)
    "sensor.wheatherstation_outdoor_temperature": ("18.5", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.wheatherstation_solar_radiation": ("650", {"unit_of_measurement": "W/m²"}),
    "sensor.wheatherstation_uv_index": ("5", {}),
    "sensor.wheatherstation_hourly_rain": ("0", {"unit_of_measurement": "mm"}),
    "sensor.wheatherstation_rain_rate": ("0", {"unit_of_measurement": "mm/h"}),
    # 14 °C classifies as "neutral" (12 < 14 < 16) — consistent with the seeded indicator state
    # below, so a real re-render of sensor.heating_cooling_indicator (triggered by a helper
    # change) cannot flip the seed to another season behind unrelated tests.
    "sensor.wheatherstation_outdoor_temperature_48h_mean": ("14.0", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    # Sun-shining binary_sensor — seeded on so evaluate_state Rule 6 (not_enough_sun)
    # does not fire unexpectedly. The template has delay_on/delay_off that prevent it
    # reaching "on" naturally within a CI test run.
    "binary_sensor.pergola_sun_shining": ("on", {}),
    # Somfy cover priority-lock sensors (UI integration — absent in CI)
    "sensor.dach_links_priority_lock_originator": ("none", {}),
    "sensor.dach_rechts_priority_lock_originator": ("none", {}),
    "sensor.dach_links_priority_lock_timer": ("0", {}),
    "sensor.dach_rechts_priority_lock_timer": ("0", {}),
    # Somfy covers (UI integration — absent in CI)
    "cover.dach_links": ("open", {"current_tilt_position": 50}),
    "cover.dach_rechts": ("open", {"current_tilt_position": 50}),
    # ComfoConnect (absent in CI)
    "select.comfoconnect_pro_temperature_profile": ("comfort", {}),
    "select.comfoconnect_pro_ventilation_preset": ("medium", {}),
    "switch.comfoconnect_pro_auto_mode": ("on", {}),
    "switch.comfoconnect_pro_away_function": ("off", {}),
    "switch.comfoconnect_pro_boost": ("off", {}),
    "climate.airflow_climate": ("auto", {"hvac_action": "fan"}),
    "number.comfoconnect_pro_boost_time": ("0", {"unit_of_measurement": "min", "min": 0, "max": 1092, "step": 1}),
    # Workday integration (absent in CI) — seeded to workday so tests are deterministic
    "binary_sensor.workday": ("on", {}),
    # Schedule helpers (UI-only, absent in CI) — workday schedule on, non-workday off by default
    "schedule.airflow_boost_workday": ("on", {}),
    "schedule.airflow_boost_non_workday": ("off", {}),
    # Flush + drying binary sensors — reset to 'off' so tests start with a clean state machine.
    # REST-setting them to 'on' in automation tests decouples the state machine from the
    # template engine's internal _state; this reset re-syncs them before each test.
    # NOTE: baseline max_humidity==target_humidity==55 → dew_point_max==dew_point_target, so the
    # flush sensor's Branch 1 and Branch 2 collapse; branch-distinguishing tests set max_humidity=60.
    "binary_sensor.airflow_humidity_flush_needed": ("off", {}),
    "binary_sensor.airflow_humidity_drying_needed": ("off", {}),
    # Heat-protection guard + combined low intent (moisture OR heat) — start clean so the decision
    # (sensor.airflow_cooling_state) does not pick up a stale low guard from a previous test.
    "binary_sensor.airflow_heat_ventilation_low_needed": ("off", {}),
    "binary_sensor.airflow_ventilation_low_needed": ("off", {}),
    # Remaining inputs of sensor.airflow_cooling_state (the single decision): its availability
    # requires every indicator to hold a value, and these two would otherwise sit 'unknown' after
    # boot until their 10-min delay elapses.
    "binary_sensor.airflow_free_cooling_available": ("off", {}),
    "binary_sensor.airflow_moisture_ventilation_low_needed": ("off", {}),
    "sensor.comfoconnect_pro_extract_air_temperature": ("21.0", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.comfoconnect_pro_extract_air_humidity": ("55", {"unit_of_measurement": "%", "device_class": "humidity"}),
    "sensor.comfoconnect_pro_extract_air_dew_point": ("12.0", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.comfoconnect_pro_outdoor_air_temperature": ("16.0", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.comfoconnect_pro_outdoor_air_dewpoint": ("8.5", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.comfoconnect_pro_outdoor_air_humidity": ("61", {"unit_of_measurement": "%", "device_class": "humidity"}),
    "sensor.comfoconnect_pro_supply_air_temperature": ("19.5", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.comfoconnect_pro_supply_air_humidity": ("45", {"unit_of_measurement": "%", "device_class": "humidity"}),
    "sensor.comfoconnect_pro_supply_fan_volume": ("150", {"unit_of_measurement": "m³/h"}),
    # Airflow filter sensors (platform:filter does not compute in CI; seed directly)
    "sensor.airflow_outdoor_temp_5min": ("16.0", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.airflow_outdoor_dew_5min": ("8.5", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.airflow_outdoor_air_humidity_5min": ("61.0", {"unit_of_measurement": "%", "device_class": "humidity"}),
    "sensor.airflow_supply_air_temp_5min": ("19.5", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.airflow_supply_air_humidity_5min": ("45.0", {"unit_of_measurement": "%", "device_class": "humidity"}),
    "sensor.airflow_extract_air_temp_5min": ("21.0", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.airflow_extract_air_humidity_5min": ("55.0", {"unit_of_measurement": "%", "device_class": "humidity"}),
    "sensor.airflow_min_indoor_dew_5min": ("12.0", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.airflow_avg_indoor_temp_5min": ("22.0", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.airflow_avg_indoor_humidity_5min": ("55.0", {"unit_of_measurement": "%", "device_class": "humidity"}),
    # Smoothed real-outdoor (weather-station) temp — gates the drying boost and heat protection.
    # Seed at target (21.5): below indoor (22) so heat protection is OFF, and not < target so the
    # drying-boost gate stays false — keeps both guards inert in the baseline.
    "sensor.airflow_wheatherstation_outdoor_temp_5min": ("21.5", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    # Heating/cooling indicator (template sensor from another package)
    "sensor.heating_cooling_indicator": ("neutral", {}),
    # Shelly Pro 3EM on the heating circuit (MQTT). Load-bearing for sensor.heating_pv_surplus,
    # which subtracts it so the surplus figure is invariant under the heat pump's own draw.
    "sensor.technikraum_heizung_heizung_power": ("0", {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}),
    # ebusd heat-pump telemetry (MQTT — no broker in CI). Values mirror a real idle reading:
    # generator off, flow ~25 °C, return ~25 °C, setback and setpoint both 21.0.
    "sensor.geotherm_heating_hvac_action": ("off", {}),
    "sensor.geotherm_heating_circuit_flow_temp": ("25.2", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.geotherm_heating_circuit_return_temp": ("24.9", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.geotherm_heating_temp_desired_low": ("21.0", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.geotherm_heating_temp_desired": ("21.0", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.geotherm_heating_hvac_mode": ("low", {}),
    # ebusd bridge status — "finished" is the steady/safe state (scan not in progress), so the
    # poll-registration automation's condition gate passes by default in tests.
    "sensor.ebusd_heating_ebusd_scan_status": ("finished", {}),
    "binary_sensor.ebusd_heating_ebusd_running": ("on", {}),
    # ebusd interlock inputs — all inactive, so the baseline permits heating.
    "binary_sensor.geotherm_heating_cooling_demand": ("off", {}),
    "binary_sensor.geotherm_heating_cooling_request": ("off", {}),
    "binary_sensor.geotherm_heating_cooling_active_uih": ("off", {}),
    "binary_sensor.geotherm_heating_hwc_active": ("off", {}),
    "binary_sensor.geotherm_heating_backup_heater": ("off", {}),
    # Loxone comfort signal — "not warm enough", i.e. the house wants heat.
    "binary_sensor.loxone_heating_heating_loxone_warm_enough": ("off", {}),
    # Compressor-cycling observation (ebusd MQTT): integral mid-pause, settings as tuned by the
    # owner (start −180 °min), lifetime counters at plausible values.
    "sensor.geotherm_heating_energy_integral": ("-90", {"unit_of_measurement": "°min"}),
    "binary_sensor.geotherm_heating_compressor_demand": ("off", {}),
    "sensor.geotherm_heating_circuit_flow_temp_desired": ("26", {"unit_of_measurement": "°C", "device_class": "temperature"}),
    "sensor.geotherm_heating_compressor_start_integral": ("-180", {"unit_of_measurement": "°min"}),
    "sensor.geotherm_heating_compressor_hysteresis": ("7", {"unit_of_measurement": "K"}),
    "sensor.geotherm_heating_backup_start_integral": ("-600", {"unit_of_measurement": "°min"}),
    "sensor.geotherm_heating_compressor_starts": ("20000", {"state_class": "total_increasing", "unit_of_measurement": "count"}),
    "sensor.geotherm_heating_compressor_hours": ("15000", {"unit_of_measurement": "h", "device_class": "duration"}),
    "sensor.geotherm_heating_yield_total": ("60000", {"unit_of_measurement": "kWh", "device_class": "energy"}),
    # Daily meters behind sensor.heating_efficiency_today (utility_meter; its source energy
    # sensors are MQTT and absent in CI, so seed the meters directly).
    "sensor.heating_yield_daily": ("0", {"unit_of_measurement": "kWh"}),
    "sensor.heating_electricity_daily": ("0", {"unit_of_measurement": "kWh"}),
}
