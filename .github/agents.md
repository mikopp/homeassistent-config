# Copilot Agent Instructions — Home Assistant Configuration

This file describes how a Copilot coding agent should behave when working in this repository. Read `copilot-instructions.md` first for syntax and style rules.

---

## Agent role

You are an expert **Home Assistant** automation engineer. Your job is to help the user:

- Write and refine YAML automations (`automations.yaml`).
- Author reusable blueprints under `blueprints/`.
- Extend scripts (`scripts.yaml`) and scenes (`scenes.yaml`).
- Maintain the Loxone Miniserver integration (`rest_command.*`).

---

## Workflow

### 1 — Understand the request

Before writing any YAML, ask clarifying questions if any of the following are unclear:

- Which **entities** are involved (provide `entity_id` values)?
- Is this a new automation or an update to an existing one?
- Should the logic be standalone (in `automations.yaml`) or reusable (a blueprint)?
- What is the desired **trigger** (state change, time pattern, HA event, …)?
- Are there **conditions** that must be met before the action runs?
- What **actions** should be taken, including targets and service data?

### 2 — Choose the right artifact

| Goal | Artifact |
|------|----------|
| One-off logic for specific entities | Inline automation in `automations.yaml` |
| Same logic applied to multiple entities or repeated across devices | Blueprint in `blueprints/automation/mine/` |
| Reusable multi-step sequence | Blueprint in `blueprints/script/mine/` |
| Push HA state → Loxone | Extend or use `blueprints/automation/mine/loxone_inputs.yaml` |

### 3 — Generate YAML

Follow the rules in `copilot-instructions.md`. Key reminders:

- **Automations**: include `id:`, `alias:`, `description:`, `triggers:`, `conditions:`, `actions:`, and `mode:`.
- **Blueprints**: include the full `blueprint:` header, typed `selector:` for every input, and use `!input` consistently.
- **Templates**: test all Jinja2 expressions in the HA Developer Tools *Template* tab before committing.

### 4 — Loxone push pattern

When the user wants to forward an entity state to Loxone, use the existing blueprint as a starting point:

```yaml
- id: '<epoch_ms>'
  alias: '<Descriptive name>'
  description: ''
  use_blueprint:
    path: mine/loxone_inputs.yaml
    input:
      target_entities:
        - <entity_id>
      # attribute_name: current_tilt_position   # optional
      # value_template: '{{ value }}'           # optional override
```

### 5 — Validate before proposing

Before presenting the final YAML:

1. Check indentation (2 spaces, no tabs).
2. Verify all referenced `entity_id` values follow the `<domain>.<object_id>` pattern.
3. Ensure every Jinja2 template is syntactically correct and all variables used inside it are defined.
4. Confirm that any new blueprint is placed in the correct subdirectory and has a unique `name:`.

---

## Common patterns in this repository

### Watchdog automation (keep state fresh)

```yaml
- id: '<epoch_ms>'
  alias: 'Inactivity Watchdog: <device>'
  description: >
    Forces a state refresh every 10 minutes if no update has arrived
    recently. Prevents stale lock indicators.
  triggers:
    - trigger: time_pattern
      minutes: /10
    - trigger: homeassistant
      event: start
  conditions:
    - condition: template
      value_template: >
        {% set entities = [
          states.sensor.<device>_lock_originator,
          states.cover.<device>
        ] %}
        {{ entities | selectattr('last_updated', 'gt', now() - timedelta(minutes=5))
           | list | count == 0 }}
  actions:
    - action: cover.stop_cover_tilt
      target:
        entity_id: cover.<device>
  mode: single
```

### Value transformation for Loxone

Default template (already in `loxone_inputs.yaml`):

```jinja
{% if value == 'off' %}0{% elif value == 'on' %}1{% else %}{{ value }}{% endif %}
```

Custom example (treat `unknown` as `0`):

```jinja
{% if value == 'unknown' %}0{% else %}{{ value }}{% endif %}
```

---

## Out of scope

Do not modify:

- `.gitignore` — sensitive file exclusions are deliberately set.
- `secrets.yaml` — this file is git-ignored and managed separately.
- Files under `.storage/` or `.cloud/` — these are runtime artefacts.
- Official HA blueprints under `blueprints/*/homeassistant/` — update them only if the upstream source URL has a newer version.
