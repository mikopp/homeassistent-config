# homeassistent-config

Personal [Home Assistant](https://www.home-assistant.io/) configuration, used to develop and version-control automations, scripts and scenes.

## Repository structure

| File / folder | Purpose |
|---|---|
| `configuration.yaml` | Main HA configuration entry point |
| `automations.yaml` | All automations (managed by the HA UI or edited manually) |
| `scripts.yaml` | Reusable scripts |
| `scenes.yaml` | Scene definitions |
| `secrets.yaml.example` | Template for `secrets.yaml` — copy and fill in real values |
| `.gitignore` | Keeps secrets and runtime files out of version control |

## Getting started

1. **Clone** this repository into your Home Assistant config directory (usually `/config` on HA OS or `~/.homeassistant` on other installs).
2. **Copy** `secrets.yaml.example` to `secrets.yaml` and fill in your credentials:
   ```bash
   cp secrets.yaml.example secrets.yaml
   ```
3. **Restart** Home Assistant to pick up the configuration.

## Development workflow

* Edit automations via the HA UI — changes are written back to `automations.yaml` automatically.
* For more complex automations or scripts, edit the YAML files directly and reload the configuration from **Developer Tools → YAML → Check & Restart**.
* Commit and push changes to this repo to keep a history of your configuration.

## Security

`secrets.yaml` is listed in `.gitignore` and will **never** be committed.  
Use `!secret <key>` references in your YAML files instead of hard-coded credentials.
