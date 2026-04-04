# Home Assistant Config — Claude Instructions

## Source of truth
This git repo IS the HA config. All changes must be made here, never via MCP tools.

## MCP usage (read-only)
The ha-mcp connection is available for DISCOVERY ONLY:
- Look up entity IDs, device names, areas, and current states
- Understand what integrations and devices exist
- Verify entity IDs before using them in automations

**Never call any ha-mcp tool that writes, changes state, or calls a service.**
Only use read tools: entity lookup, area listing, device listing, state queries.

## Workflow
1. Use ha-mcp to discover relevant entities/areas
2. Write or edit YAML files in this repo
3. User will deploy via `git pull` on the HA host

## Config structure
This repo IS the HA config directory. All automations, scripts, blueprints, and helpers
are defined here in YAML files — not in the HA UI or via MCP tools.

- `automations.yaml` — all automations (single file, `!include`d from configuration.yaml)
- `scripts.yaml` — all scripts
- `scenes.yaml` — all scenes
- `configuration.yaml` — main config; also defines helpers (input_boolean, input_number, etc.)
- `blueprints/automation/mine/` — custom automation blueprints
- `blueprints/automation/homeassistant/` — official HA blueprints