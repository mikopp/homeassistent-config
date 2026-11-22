# Heating — raw-history retention (follow-up)

## Overview

`configuration.yaml` keeps raw state history 14 days (`recorder: purge_keep_days: 14`, was 5) so
the heating baselines survive until their comparison. Long-term statistics are a separate store
and unaffected. This was meant to be temporary: revert to 5 once the tuning work no longer needs
raw history older than 5 days.

Everything else this plan covered is done and lives in its homes: the `/set out` bridge rule
(`doc/heating_pv_boost/notes.md` "Invariants", device VWS-41), the counting rules (the note's
"Decisions in force"), the `count` unit on `sensor.geotherm_heating_compressor_starts` (YAML).
SOC 50 is slab plan step 8c. The story is in git history (#129-#134 era, this plan's earlier text).

Knowledge homes touched at close: `configuration.yaml` comment only.

## Steps

- [TODO] 1. Owner decides whether to revert to 5 days (the cycling plan closed 2026-11-21; the
      heating-curve tuning in `plans/heating-curve-tuning.md` may still read raw history). Before
      deciding, optionally check the DB size (`sensor.database_size` or `home-assistant_v2.db`)
      to see what 14 days cost. If reverting: `purge_keep_days: 5`, rewrite the comment above it
      (drop the pointer to this plan), deploy with an HA restart (recorder config).

## Status

- [TODO] 1. Retention: keep 14 or revert to 5 (owner)

## Close
- [TODO] Close: point the `configuration.yaml` comment to its final reason (or none), drop this
  plan from `doc/heating_pv_boost/notes.md` "Related", delete this plan (`doc/KNOWLEDGE.md#K-6`)
