---
name: yaml
description: Best practices for Home Assistant automations, templates, blueprints, scripts, scenes, and YAML configuration
---

# Home Assistant YAML & Automation Best Practices

This skill provides comprehensive patterns for writing correct, efficient, and maintainable HA configuration.

---

## Quick Checklist (Before Every Automation)

- [ ] Has `id:` (required for traces)
- [ ] Has descriptive `alias:`
- [ ] Has `description:` explaining behavior
- [ ] Uses appropriate `mode:` (single/restart/queued/parallel)
- [ ] All templates have defaults: `| float(0)`, `| int(0)`
- [ ] Trigger IDs for complex automations
- [ ] Conditions ordered by likelihood of failure (fastest first)

---

## 1. Automation Modes

| Mode | Behavior | Use When |
|------|----------|----------|
| `single` | Blocks new runs while running | Default - prevents overlap |
| `restart` | Stops current, starts new | Motion lights, re-triggerable timers |
| `queued` | Runs sequentially in order | Device actions (locks, covers, climate) |
| `parallel` | Independent concurrent runs | Notifications, non-conflicting actions |

```yaml
automation:
  - id: example_automation
    alias: "Example Automation"
    mode: queued
    max: 5                    # Max concurrent/queued runs (default: 10)
    max_exceeded: silent      # silent, debug, info, warning, error, critical
```

**Rule:** Use `mode: restart` for motion-activated lights. Use `mode: queued` for presence-based automations that may fire rapidly.

---

## 2. Triggers

### Prefer State Triggers Over Template Triggers

```yaml
# GOOD - Efficient
trigger:
  - platform: numeric_state
    entity_id: sensor.temperature
    above: 25

# AVOID - Evaluates on every state change
trigger:
  - platform: template
    value_template: "{{ states('sensor.temperature') | float > 25 }}"
```

### Use Trigger IDs

```yaml
trigger:
  - id: "motion_on"
    platform: state
    entity_id: binary_sensor.motion
    to: "on"
  - id: "motion_off"
    platform: state
    entity_id: binary_sensor.motion
    to: "off"
    for:
      minutes: 5    # Timeout IN trigger, not as delay action
```

### Multiple Entities on Same Trigger

```yaml
trigger:
  - platform: state
    entity_id:
      - binary_sensor.motion_1
      - binary_sensor.motion_2
      - binary_sensor.motion_3
    to: "on"
```

### Motion Light Pattern (Recommended)

```yaml
# Put timeout in the "no motion" trigger's for: parameter
trigger:
  - platform: state
    entity_id: binary_sensor.motion
    from: 'off'
    to: 'on'
    id: 'on'
  - platform: state
    entity_id: binary_sensor.motion
    from: 'on'
    to: 'off'
    id: 'off'
    for:
      minutes: 5    # Timeout here, NOT as a delay action!
```

---

## 3. Conditions

### Order by Likelihood of Failure (Fastest Checks First)

```yaml
condition:
  # Quick checks first (most likely to fail)
  - condition: state
    entity_id: input_boolean.vacation_mode
    state: "off"
  - condition: time
    after: "07:00:00"
    before: "23:00:00"
  # More complex checks last
  - condition: numeric_state
    entity_id: sensor.lux
    below: 100
```

### Prefer Native Over Template Conditions

```yaml
# GOOD - Native condition
- condition: state
  entity_id: input_select.home_profile
  state:
    - "Away"
    - "Vacation"
  match: any

# AVOID for simple checks - Template condition
- condition: template
  value_template: "{{ states('input_select.home_profile') in ['Away', 'Vacation'] }}"
```

---

## 4. Actions

### Use Choose for Conditional Logic

```yaml
action:
  - choose:
      - conditions:
          - condition: trigger
            id: "motion_on"
        sequence:
          - action: light.turn_on
            target:
              entity_id: light.room
      - conditions:
          - condition: trigger
            id: "motion_off"
        sequence:
          - action: light.turn_off
            target:
              entity_id: light.room
    default:
      - action: notify.mobile_app
        data:
          message: "Unexpected trigger"
```

### Use Parallel for Independent Actions

```yaml
action:
  - parallel:
      - action: notify.mobile_app
        data:
          message: "Motion detected"
      - action: light.turn_on
        target:
          entity_id: light.porch
```

### Use continue_on_error for Fault Tolerance

```yaml
action:
  - action: light.turn_on
    target:
      entity_id: light.possibly_offline
    continue_on_error: true
  - action: notify.mobile_app
    data:
      message: "Attempted to turn on light"
```

### Better Thermostat Pattern

**ALWAYS call `climate.turn_on` before `climate.set_temperature` for Better Thermostat entities:**

```yaml
# WRONG - hvac_mode ignored when thermostat is "off"
- action: climate.set_temperature
  data:
    hvac_mode: heat
    temperature: 22
  target:
    entity_id: climate.bathroom_thermostat

# CORRECT - Always works
- action: climate.turn_on
  target:
    entity_id: climate.bathroom_thermostat
- action: climate.set_temperature
  data:
    hvac_mode: heat
    temperature: 22
  target:
    entity_id: climate.bathroom_thermostat
```

---

## 5. Templates (Jinja2)

### ALWAYS Use Defaults

```jinja2
{{ states('sensor.temp') | float(0) }}           {# Default 0 if invalid #}
{{ states('sensor.count') | int(0) }}            {# Integer with default #}
{{ state_attr('entity', 'attr') | default(0) }}  {# Attribute default #}
```

**Critical:** Since HA 2021.10, template filters error on invalid input without defaults.

### Check Availability

```jinja2
{% if has_value('sensor.temperature') %}
  {{ states('sensor.temperature') | float }}
{% else %}
  unavailable
{% endif %}
```

### Template Sensor Pattern

```yaml
template:
  - sensor:
      - name: "Target Temperature Study"
        unique_id: target_temperature_study      # Required for UI customization
        unit_of_measurement: "°C"
        device_class: temperature                 # Required for proper display
        state: >
          {% set profile = states('input_select.home_profile') %}
          {% if profile in ['Away', 'Night', 'Vacation'] %}
            {{ states('input_number.temp_global_away') | float(16) }}
          {% else %}
            {{ states('input_number.temp_study_comfort') | float(22) }}
          {% endif %}
        availability: >
          {{ states('input_select.home_profile') not in ['unavailable', 'unknown'] }}
```

### Performance Considerations

1. **Avoid `now()` in high-frequency templates** - causes minute-level refresh
2. **Use domain-specific queries:** `states.light` not `states`
3. **Rate limits:** All-states templates: 1/minute; domain templates: 1/second

### Trigger-Based vs State-Based Sensors

| Use Case | Recommendation |
|----------|----------------|
| Real-time monitoring | State-based |
| Rate-limited updates | Trigger-based |
| Expensive calculations | Trigger-based |

```yaml
# Trigger-based (updates only on trigger)
template:
  - trigger:
      - platform: time_pattern
        minutes: "/5"
    sensor:
      - name: "Scheduled Update Sensor"
        state: "{{ states('sensor.input') | float(0) * 2 }}"
```

---

## 6. Blueprints

### Blueprint Schema

```yaml
blueprint:
  name: Motion-activated Light
  description: |
    Turn lights on when motion is detected.
    Supports multiple sensors and configurable timeout.
  domain: automation
  author: Your Name
  homeassistant:
    min_version: 2024.6.0
  input:
    motion_sensor:
      name: Motion Sensor
      selector:
        entity:
          filter:
            - domain: binary_sensor
              device_class: motion
```

### Key Limitation: enabled: false NOT SUPPORTED

```yaml
# WRONG - Causes HA startup error
- id: my_automation
  enabled: false          # NOT ALLOWED in blueprints
  use_blueprint:
    path: custom/my_blueprint.yaml
```

**Workaround:** Remove from YAML file, disable via UI after creation.

### Using Inputs in Templates

**Inputs must be exposed as variables first:**

```yaml
variables:
  target: !input target_entity

triggers:
  - trigger: state
    entity_id: !input target_entity   # OK in trigger

actions:
  - action: light.turn_on
    target:
      entity_id: "{{ target }}"       # Use variable, NOT !input
```

### For Template Triggers Use trigger_variables

```yaml
trigger_variables:
  my_entity: !input sensor_entity

triggers:
  - trigger: template
    value_template: "{{ states(my_entity) | float > 25 }}"
```

### Input Sections (HA 2024.6.0+)

```yaml
input:
  motion_settings:
    name: Motion Settings
    icon: mdi:motion-sensor
    collapsed: false
    input:
      motion_sensor:
        name: Motion Sensor
        selector:
          entity:
            domain: binary_sensor
```

---

## 7. Scripts

### Script Modes

Same as automation modes: `single`, `restart`, `queued`, `parallel`

### Script Fields (Parameters)

```yaml
script:
  notify_user:
    alias: "Notify User"
    fields:
      message:
        name: Message
        required: true
        selector:
          text:
      title:
        name: Title
        default: "Home Assistant"
        selector:
          text:
    sequence:
      - action: notify.mobile_app
        data:
          title: "{{ title }}"
          message: "{{ message }}"
```

### Calling Scripts

```yaml
# Method 1: Direct call (blocking - waits for completion)
action:
  - action: script.notify_user
    data:
      message: "Alert!"

# Method 2: script.turn_on (non-blocking - continues immediately)
action:
  - action: script.turn_on
    target:
      entity_id: script.notify_user
    data:
      variables:
        message: "Alert!"
```

---

## 8. Scenes

### When to Use

| Component | Use When |
|-----------|----------|
| **Scene** | Setting multiple devices to specific states simultaneously |
| **Script** | Reusable action sequences called from multiple places |
| **Automation** | Event-driven responses requiring triggers |

### Scene Snapshots (Save/Restore)

```yaml
# Save current state before change
- action: scene.create
  data:
    scene_id: before_window_open
    snapshot_entities:
      - climate.ecobee
      - light.ceiling_lights

# Later, restore saved state
- action: scene.turn_on
  target:
    entity_id: scene.before_window_open
```

**Common use cases:**
- Window open/close (save HVAC state, restore on close)
- Cleaning mode (all lights 100%, then restore)
- Doorbell notification (flash lights, then restore)
- TV/Media playback (dim lights, restore after)

---

## 9. Common Gotchas

### wait_for_trigger vs wait_template

- `wait_for_trigger`: Waits for state **change** - if already met, waits forever!
- `wait_template`: Continues immediately if condition already true

```yaml
# DANGER - If motion already on, waits forever
- wait_for_trigger:
    - platform: state
      entity_id: binary_sensor.motion
      to: "on"

# SAFE - Continues if motion already on
- wait_template: "{{ is_state('binary_sensor.motion', 'on') }}"
```

### Preventing Startup False Triggers

```yaml
template:
  - trigger:
      - platform: event
        event_type: event_template_reloaded
      - platform: homeassistant
        event: start
    binary_sensor:
      - name: "HA Initializing"
        unique_id: ha_initializing
        state: "true"
        auto_off: 10
```

Then add condition to sensitive automations:
```yaml
condition:
  - condition: state
    entity_id: binary_sensor.ha_initializing
    state: "off"
```

### input_number: Never Use initial:

```yaml
# WRONG - Value resets after every HA restart
input_number:
  temp_study_eco:
    initial: 19     # REMOVE THIS!

# CORRECT - Value persists between restarts
input_number:
  temp_study_eco:
    min: 14
    max: 22
    step: 0.5
    unit_of_measurement: "°C"
```

---

## 10. Naming Conventions

### Automation Naming

```yaml
# Category prefix with action
- alias: 'Climate: Turn off HVAC when window opened'
- alias: 'Light: Motion-activated hallway'
- alias: 'Vacuum: Auto-Start if Idle 3 Days'
```

### Entity Naming

| Pattern | Example |
|---------|---------|
| What_Where | `binary_sensor.motion_office` |
| Room-First | `light.hall_main` |

**Rules:**
- Avoid brand names in entity IDs (use `motion_study` not `aqara_p1_motion_study`)
- Entity IDs should remain stable (rename via friendly names)
- Use Areas and Labels for organization

---

## 11. File Organization

### Packages Pattern (Recommended)

```yaml
# configuration.yaml
homeassistant:
  packages: !include_dir_named packages
```

**Package file** (`packages/vacuum.yaml`):
```yaml
input_boolean:
  vacuum_enabled:
    name: Vacuum Enabled

automation:
  - alias: 'Vacuum: Auto-Start if Idle 3 Days'
    id: vacuum_auto_start
    # ...

script:
  start_vacuum:
    alias: Start Vacuum
    sequence: # ...
```

### Directory Splitting

```yaml
# configuration.yaml
automation: !include_dir_merge_list automations/
template: !include_dir_merge_list templates/
```

---

## 12. Watchdog Patterns

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

---

## Summary Rules

### Must-Have (Always Do)

1. **Always include `id:`** on automations (required for traces)
2. **Always use `unique_id:`** on template sensors (enables UI customization)
3. **Always provide defaults** in templates: `| float(0)`, `| int(0)`
4. **Always include `device_class:`** on sensors
5. **Prefer state triggers** over template triggers
6. **Use `mode: queued`** for event-driven automations
7. **Put timeout in trigger's `for:`** not as delay action

### Avoid (Never Do)

1. **Don't use `enabled: false` in blueprints** - not supported
2. **Don't hardcode values** - use `input_number` helpers
3. **Don't use `now()` in high-frequency templates**
4. **Don't edit `.storage` files directly** - use APIs
5. **Don't use `sed`/`awk` on YAML** - risk of corruption
6. **Don't use `initial:` in input_number** - breaks persistence

---

## Documentation References

- [Automation Modes](https://www.home-assistant.io/docs/automation/modes/)
- [Blueprint Schema](https://www.home-assistant.io/docs/blueprint/schema/)
- [Blueprint Selectors](https://www.home-assistant.io/docs/blueprint/selectors/)
- [Templating](https://www.home-assistant.io/docs/configuration/templating/)
- [Script Syntax](https://www.home-assistant.io/docs/scripts/)
- [Scene Integration](https://www.home-assistant.io/integrations/scene/)
