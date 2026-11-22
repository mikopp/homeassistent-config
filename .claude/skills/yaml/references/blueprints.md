# Blueprints

Part of the `yaml` skill (general HA style; this repo's binding rules: `.claude/rules/ha-yaml.md`).


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
