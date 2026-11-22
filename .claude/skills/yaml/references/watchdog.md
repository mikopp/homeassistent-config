# Watchdog patterns

Part of the `yaml` skill (general HA style; this repo's binding rules: `.claude/rules/ha-yaml.md`).


### Auto-Off After Duration

```yaml
- alias: 'Light WatchDog - Auto-off after 1 hour'
  trigger:
    - platform: state
      entity_id:
        - light.hallway_lights
        - light.bathroom_lights
      to: 'on'
      for: '01:00:00'
  action:
    - action: homeassistant.turn_off
      data:
        entity_id: "{{ trigger.entity_id }}"
```

### Unavailable Entity Recovery

```yaml
- alias: 'Device Recovery'
  mode: queued
  trigger:
    - platform: state
      entity_id: light.led_strip
      to: "unavailable"
      for: "00:00:30"
  action:
    - repeat:
        while:
          - condition: state
            entity_id: light.led_strip
            state: "unavailable"
          - condition: template
            value_template: "{{ repeat.index <= 5 }}"
        sequence:
          - action: switch.turn_off
            entity_id: switch.led_power
          - delay: "00:00:05"
          - action: switch.turn_on
            entity_id: switch.led_power
          - delay: "00:00:10"
```
