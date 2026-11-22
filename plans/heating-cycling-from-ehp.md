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

Left: two device questions behind the mode table, and one owner cleanup.

Knowledge homes this plan will update:
- Device `runs.md`, `behaviour.md` and `evidence.md` (VWS-13, VWS-15, VWS-16).
- Design HPB-2 table and Known gaps; notes "Energy modes" (the 30-day line, after step 15).

## Hypotheses

- UNPROVEN: `hvac_action` reads `cooling` (`ehp/Status` hcmode `1`) while the unit cools. It has
  never been seen; the package has only run in the heating season. Fallback signal:
  `uih/CoolingActive`. Settled by step 14.
- HYPOTHESIS (agent analysis of statistics, 2026-11-22): every hot-water charge ends with
  2–4 min of compressor at heating power (~1.9 kW) into the heating circuit. That tail is
  `HwcLaggingTime` ("WP Nachlaufzeit WW" = heat-pump run-on, 3 min here), not a circulation pump
  running on. What the statistics showed:
  - In 8 of 8 evening ends (2026-11-15…22): an `active_heating` slice of 0.064–0.117 kWh
    (≈ 2–3.7 min at 1.9 kW), with no other heating run in that hour.
  - Morning ends: the same slice wherever it can be told apart from a heating run.
  - 2026-11-22 17:30 end: VF2 24.9 → 36.8 °C, so the water went to the floor; the integral went
    −104 → −73 °min; the return was back at slab level (25.4 °C) in the same bucket, so the
    valve was already on heating.
  - `water_heating` booked 0 from the first bucket after the compressor stopped. So `hvac_action`
    leaves `water` before the compressor stops, and the HPB-2 "hot-water run-on" row
    (`Hc1Pump` on + `water`) has never fired in the ends checked.
  - The `off` meter booked 0 kWh in 8 days and `passive_heating` ~82 W in every hour without a
    run. So `ehp/Hc1Pump` reads on all the time in the heating season (a stuck reading would
    look the same) and cannot show a run-on.

  This contradicts VWS-13's "either straight to the idle pump level or a short heating segment"
  (device VWS-13): its "straight to idle" example (2026-11-20 05:50–06:16) has 0.064 kWh `active_heating`
  in the 06:15 bucket, which the 5 min power mean hid. Not yet recorded in the device doc:
  5 min statistics only, no valve read, no second-level timing. Settled by step 17.

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
17. [TODO] Hot-water end (device VWS-13, design HPB-2 Known gaps); tests the hypothesis above.
    - Owner test: during one hot-water end, run `ebusctl read -f -c ehp HwcHcValve` and time the
      gap from the end of the charge (`hvac_action` leaves `water`) to `ehp/Comp` off. About
      3 min with the valve on heating confirms that the tail is `HwcLaggingTime` into the
      heating circuit.
    - Confirmed: fix VWS-13 (new T row: every charge ends with the compressor tail; the
      `HwcLaggingTime` link tagged by the test). Close the pump question in `behaviour.md` Open
      questions (`Hc1Pump` is always on in the heating season). In HPB-2, drop the
      "hot-water run-on" row or note that it never fires; the tail is already booked
      `active_heating`, the right bucket since the heat goes to the floor. Close that Known gap.
    - Coordinate with `plans/heating-curve-tuning.md` step 0.12 (why the compressor runs on into
      heating after hot water): if the tail is every charge's `HwcLaggingTime`, 0.12 is
      answered too.

## Status

- [DONE] Steps 1-12 and 16: implemented, deployed, checked live 2026-11-21.
- [TODO] 17 (owner valve test; any time in the heating season)
- [TODO] 14 (cooling season)
- [TODO] 15 (owner, earliest about 2026-12-12)
- [TODO] 13 Close: after 14, 15 and 17, or once the owner agrees to close without the cooling
  check. In that case, note the cooling row as UNPROVEN in design HPB-2.

## Close
13. [TODO] Close: results to device doc, design HPB-2 and notes; story → background; update
    the pointers (design Known gaps, device `behaviour.md` Open questions); delete this plan
    (`doc/KNOWLEDGE.md#K-6`).
