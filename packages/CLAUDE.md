# Packages — progressive-loading index

This file is intentionally a thin index. Package-specific knowledge (hardware quirks, design rules,
verified register decodes) lives in **one file per package** under `packages/notes/`, so it is not
paid for in context unless you actually work on that package.

## Rule for agents
**Before reading or editing `packages/<name>.yaml`, read `packages/notes/<name>.md` if it exists.**
Do not read the notes of packages you are not touching.

## Rule for adding/changing notes (applies to every future package)
- Package-specific knowledge goes in `packages/notes/<name>.md` (same basename as the YAML file).
  **Never add it to this file or to the root `CLAUDE.MD`.**
- When you create a new `packages/<name>.yaml` and have notes worth keeping, create
  `packages/notes/<name>.md` and add a row to the index below (one line: when to read it).
- Keep this file to the index and these rules only.

## Index

| Package | Notes | Read when… |
|---|---|---|
| `airflow_cooling.yaml` | `notes/airflow_cooling.md` | touching ComfoConnect boost/preset/auto logic or the ventilation controller |
| `energy.yaml` | `notes/energy.md` | touching Energy Dashboard sensors or wallbox/PV wrappers |
| `heating_pv_boost.yaml` | `notes/heating_pv_boost.md` | touching ebusd/Vaillant registers, poll registration, or heating/cooling control |
| `pergola.yaml` | — (none yet) | — |
| `victron.yaml` | — (none yet) | — |
| `heating_cooling_indicator.yaml` | — (none yet) | — |
