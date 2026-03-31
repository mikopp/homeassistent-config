# GitHub Copilot Instructions — Home Assistant Configuration

## Repository overview

This repository contains a [Home Assistant](https://www.home-assistant.io/) instance configuration running **HA 2026.3.4**. It is a YAML-only setup (no packages directory) with a direct Loxone Miniserver integration via REST commands.

Key files and directories:

| Path | Purpose |
|------|---------|
| `configuration.yaml` | Root HA config; loads automations, scripts, scenes and defines REST commands |
| `automations.yaml` | All automations (flat list, HA-managed) |
| `scripts.yaml` | All scripts |
| `scenes.yaml` | All scenes |
| `blueprints/automation/homeassistant/` | Official HA automation blueprints |
| `blueprints/automation/mine/` | Custom automation blueprints (e.g. `loxone_inputs.yaml`) |
| `blueprints/script/homeassistant/` | Official HA script blueprints |
| `.gitignore` | Excludes `secrets.yaml`, `*.db`, logs, `.storage/`, `.cloud/` |

## Language and syntax rules

- All configuration files are **YAML**. Use 2-space indentation throughout.
- Jinja2 templating is used inside HA `template:`, `value_template:`, `variables:`, and `!input` blocks. Wrap templates in double-quoted strings or use the block-scalar (`>-` / `|-`) form to avoid YAML parse errors.
- Use the modern HA syntax for triggers, conditions and actions (list-form with a `trigger:` / `condition:` / `action:` key per step), e.g.:
  ```yaml
  triggers:
    - trigger: state
      entity_id: sensor.example
  actions:
    - action: light.turn_on
      target:
        entity_id: light.example
  ```
- For automations in `automations.yaml`, **always** include a unique numeric `id:` (epoch-style, e.g. `'1771534982149'`), an `alias:`, and optionally a `description:`.
- For blueprints, include a complete `blueprint:` header block (`name`, `description`, `domain`, and `input` definitions with selectors).

## Loxone integration

The instance communicates with a Loxone Miniserver at `192.168.1.92` using two REST commands defined in `configuration.yaml`:

- `rest_command.send_to_loxone` — sends a single value to a Virtual Input:
  ```
  GET http://<user>:<pass>@192.168.1.92/jdev/sps/io/<input_name>/<value>
  ```
- `rest_command.update_loxone` — generic parameterised call using `{{ parameter }}`.

When writing automations or blueprints that push HA state to Loxone:
1. Use the `mine/loxone_inputs.yaml` blueprint as the canonical pattern.
2. The `input_name` should be `trigger.to_state.object_id` (optionally suffixed with `.attribute_name`).
3. Apply the default value-transformation template that converts `on`→`1`, `off`→`0`, and passes numeric values through unchanged.

## Blueprint authoring guidelines

1. Place **custom** blueprints under `blueprints/automation/mine/` or `blueprints/script/mine/`.
2. Place **official/community** blueprints under the matching `homeassistant/` subdirectory and include the `source_url:` field.
3. Every blueprint `input:` must have `name:`, `description:`, and a `selector:`. Provide sensible `default:` values for optional inputs.
4. Prefer `mode: parallel` for blueprints that handle multiple independent entities; use `mode: single` or `mode: restart` where appropriate.
5. Use `!input` to reference user-supplied values; store them in `variables:` when you need to manipulate them inside templates.

## Automation authoring guidelines

1. Never use the deprecated `platform:` key for triggers — use `trigger:` instead.
2. Group related automations with a common alias prefix (e.g. `"Dach Links: ..."`, `"Dach Rechts: ..."`).
3. Prefer blueprint-based automations (`use_blueprint:`) over copy-pasted YAML when the same logic applies to multiple entities.
4. Watchdog automations (periodic + `homeassistant` start triggers) are the preferred pattern for keeping state fresh when a polling device is involved.

## Security

- Credentials (Loxone username/password, IP addresses) should live in `secrets.yaml` (already git-ignored) and be referenced with `!secret <key>`.  
  In `secrets.yaml`, store the full base URL (since `!secret` must be a standalone scalar, not embedded in a string):
  ```yaml
  # secrets.yaml
  loxone_base_url: "http://myuser:mypass@192.168.1.92"
  ```
  Then reference it in `configuration.yaml`:
  ```yaml
  rest_command:
    send_to_loxone:
      url: "!secret loxone_base_url/jdev/sps/io/{{ input_name }}/{{ value }}"
  ```
  Because `!secret` replaces a complete YAML scalar, the recommended approach is to store the entire URL template in `secrets.yaml` and reference it with a single `!secret` tag:
  ```yaml
  # secrets.yaml
  loxone_send_url: "http://myuser:mypass@192.168.1.92/jdev/sps/io/{{ input_name }}/{{ value }}"

  # configuration.yaml
  rest_command:
    send_to_loxone:
      url: !secret loxone_send_url
  ```
  If you see hard-coded credentials, flag them and suggest moving them to `secrets.yaml`.
- Never commit `secrets.yaml`, `*.db`, log files, or `.storage/` — these are already in `.gitignore`.

## Validation

There is no automated CI pipeline in this repository. Before committing:

1. Use the Home Assistant **Configuration Validation** tool in the HA UI (*Developer Tools → Check and Restart → Check Configuration*) or the `hass --script check_config` CLI command.
2. Run a YAML lint pass locally if available (`yamllint .`).
3. For blueprints, import them into a test HA instance and verify all inputs render correctly.
