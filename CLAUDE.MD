# Home Assistant Config — Claude Instructions

## Source of truth
This git repo IS the Home Assistant config. All changes must be made here, never via MCP tools.

## Important constraints for this project:
1. ALWAYS create/maintain a feature specific implementation plan file in the `plans` folder. 
2. NEVER start implementation without explicit approval
3. ALWAYS await step-by-step instructions before coding
4. ALWAYS update the plan file's status section after each step
5. ALWAYS summarize what was done before asking for next steps
6. ALWAYS write comments that describe each part of the implementation in the source code file.

## MCP usage (read-only)
The ha-mcp connection is available for DISCOVERY ONLY:
- Look up entity IDs, device names, areas, and current states
- Understand what integrations and devices exist
- Verify entity IDs before using them in automations

**Never call any ha-mcp tool that writes, changes state, or calls a service.**
Only use read tools: entity lookup, area listing, device listing, state queries.

## Workflow
1. Make sure you have a plan to use as an implementation plan, ask the user if necessary
2. Use ha-mcp to discover relevant entities/areas
3. update and write the feature specific configuration upon explicit approval
4. User will deploy via `git pull` on the HA host, NEVER do that yourself

## Config structure
This repo IS the Home Assistant config directory. All automations, scripts, blueprints, and helpers
are defined here in YAML files — not in the HA UI or via MCP tools.

### Global files (keep lean — no feature-specific content)
- `configuration.yaml` — loads packages, includes automations/scripts/scenes, global integrations only
- `automations.yaml` — only automations that span multiple features or have no natural feature home
- `scripts.yaml` — same principle as automations.yaml
- `scenes.yaml` — scenes
- `blueprints/automation/mine/` — custom automation blueprints
- `blueprints/automation/homeassistant/` — official HA blueprints

### Feature packages (`packages/<feature>.yaml`)
Each feature gets its own file under `packages/`. A package file may contain any combination of:
`input_boolean`, `input_number`, `input_text`, `input_select`, `input_datetime`,
`template`, `automation`, `script`, `sensor`, `binary_sensor`, etc.

HA merges all package keys into the global config automatically via:
```yaml
homeassistant:
  packages: !include_dir_named packages
```

**Rule:** When adding anything for a named feature (e.g. pergola, irrigation, alarm),
create or edit `packages/<feature>.yaml`. Do NOT add it to configuration.yaml or
the global automations/scripts files.

Current packages:
- `packages/pergola.yaml` — pergola roof automation (helpers, template sensors, automations, scripts)