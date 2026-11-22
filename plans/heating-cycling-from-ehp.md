# Heating — run statistics from the ehp: open checks

## Overview

Run statistics now come from the ehp's own counters and `ehp/Comp`. Energy and efficiency are
split by `sensor.heating_energy_mode`. All of this is implemented and deployed. Where it lives:
- The mode table and design: design HPB-2.
- Entities and owner decisions: `doc/heating_pv_boost/notes.md` "Energy modes".
- The unit's run behaviour: device VWS-11…13.
- `ehp/Comp` lag against the supply draw: device `interface.md`.
- The return temperature during a hot-water charge: device VWS-12.
The story is in git history (#161-#168, this plan's earlier text).

Left: the cooling check behind the mode table, and one owner cleanup.

Knowledge homes this plan will update:
- Device `behaviour.md`, `cooling.md` and `evidence.md` (VWS-15, VWS-16).
- Design HPB-2 table and Known gaps; notes "Energy modes" (the 30-day line, after step 15).

## Hypotheses

- UNPROVEN: `hvac_action` reads `cooling` (`ehp/Status` hcmode `1`) while the unit cools. It has
  never been seen; the package has only run in the heating season. Fallback signal:
  `uih/CoolingActive`. Settled by step 14.

## Steps

14. [TODO] First cooling period (not before cooling season):
    - Confirm `hvac_action` reads `cooling`. If not, switch the HPB-2 cooling row to
      `uih/CoolingActive` (owner).
    - Log the outdoor temperature, `mc/OtShutdownLimit` and `CoolingStartOffsetHc2` at the first
      cooling start and stop. This settles the release (device VWS-16 [ASSUMED]).
    - Note whether a `TempDesired` change moves the release.
    - Confirm cooling keeps running with heating mode `off` (device VWS-15, design HPB-1 Known
      gaps).
15. [TODO] Owner: delete `sensor.heating_yield_by_mode_active_heating` and `_passive_heating`
    (unavailable) from the UI and from statistics. Not before 30 days after #164 reached the
    system: the 30-day yield sum reads them. Check the `days` attribute of
    `space_heating_yield_30d` first (8.9 on 2026-11-21, so the earliest is about 2026-12-12).
    Then drop the "Rolling 30 days" pre-merge clause from notes "Energy modes".

## Status

- [DONE] Steps 1-12 and 16: implemented, deployed, checked live 2026-11-21.
- [DONE] 17: the hot-water end is settled from statistics (device VWS-13); no valve test needed.
- [TODO] 14 (cooling season)
- [TODO] 15 (owner, earliest about 2026-12-12)
- [TODO] 13 Close: after 14 and 15, or once the owner agrees to close without the cooling
  check. In that case, note the cooling row as UNPROVEN in design HPB-2.

## Close
13. [TODO] Close: results to device doc, design HPB-2 and notes; story → background; update
    the pointers (design Known gaps, device `behaviour.md` Open questions); delete this plan
    (`doc/KNOWLEDGE.md#K-6`).
