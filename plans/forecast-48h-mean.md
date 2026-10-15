# Forecast 48h mean sensor

## Goal
`sensor.wheatherstation_outdoor_temperature_48h_forecast_mean`: mean of the hourly outdoor
temperature forecast for the next 48 h, refreshed every hour. Sits next to the measured
`sensor.wheatherstation_outdoor_temperature_48h_mean` in `packages/heating_cooling_indicator.yaml`
(and its group). Source: `weather.home` (supports daily + hourly, `supported_features: 3`).

## Design
- Trigger-based `template:` sensor: the forecast is only available as the response of
  `weather.get_forecasts` (the `forecast` attribute was removed in HA 2024.3).
- Triggers: `time_pattern` minute 0 (hourly) + HA start.
- Averages hourly entries with `now-1h <= datetime < now+48h`.
- Fewer than 48 usable hours → `unknown` (short/empty provider forecast must not skew the mean).
- Not wired into `sensor.heating_cooling_indicator` yet — decision for a follow-up.

## Open points
- Window confirmed by the user as 48 h ("next 40h" in the first request was a typo).
- Area "Outdoor" (`area_id: outdoor`) cannot be set from template YAML (`device:`/area keys are not
  supported there). Assign once in the UI after deploy, like the measured 48h mean.
- Unverified on the live instance: provider horizon of `weather.home` hourly forecast (needs
  >= 48 h), field names of the response. Check in Developer Tools → Actions
  (`weather.get_forecasts`, type hourly).
- No pytest: the test harness has no weather entity that answers `weather.get_forecasts`.

## Status
- [x] Sensor added to `packages/heating_cooling_indicator.yaml`, added to the group.
- [ ] yamllint / CI config check.
- [ ] Deploy, assign area Outdoor in UI, verify value against the measured mean.
- [ ] Decide whether the indicator should blend measured + forecast mean.
