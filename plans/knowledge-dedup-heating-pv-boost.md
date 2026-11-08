# Knowledge dedup: heating_pv_boost

**Status:** Steps 1-6 DONE (on `claude/gallant-thompson-yz8dss`); step 7 in review. Follow-up 2 of 5 from PR #141 (knowledge structure, merged).
Each step needs explicit approval (root CLAUDE rules 2-5).
**Depends on:** conventions, guards, `doc/` layout: satisfied by PR #141; `.github/scripts/yaml_semantic_equal.py` (added by PR #144;
if that is not merged yet, take the script from its branch).
Branch `claude/knowledge-dedup-heating` off `master`.
**Line numbers** below are from `master` `da0d742` (2026-11-07). Re-check them first.

## Overview
- **Note too big for auto-load:** `packages/notes/heating_pv_boost.md` is 23.5 KB (≈ 5.9k tokens)
  and loads on every heating edit. It mixes current facts, register decodes, one-day snapshots and
  an investigation log.
- **YAML comments:** `packages/heating_pv_boost.yaml` comments are 48 % of bytes (≈ 7.4k tokens),
  about 25 % of that history.
- **No design doc yet:** `plans/ebusd-pv-heating-optimization.md` (Phases 2-3 still open) stays a
  plan. Distil it into `doc/heating_pv_boost/design.md` only once it is done; out of scope here.

Target:
- `packages/notes/heating_pv_boost.md` ≈ 12 KB, current facts only.
- `packages/notes/heating_pv_boost-registers.md` ≈ 5 KB register decodes: not imported, linked
  from the note, grep-able.
- `doc/heating_pv_boost/background.md` ≈ 6 KB.

Expected cost: Read + note 21.4k → ~14k tokens. No behaviour change.

## Steps

### Phase A: note split
1. [DONE] Split the note:
   | Section | Action |
   |---|---|
   | Header, bus participants, transport allowlist | keep |
   | Baseline method | keep (tied to live plan `heating-baseline-…`) |
   | Payload format, poll registration, enum forms | keep, condense (poll ≈ 2.2 KB → 1 KB) |
   | Register decodes | → `heating_pv_boost-registers.md`; "live-confirmed 2026-10-17" provenance → background |
   | Compressor tuning registers | decodes → registers file; "values that day" snapshot → background |
   | Owner-side configuration (2026-10-30) | keep |
   | Hardware limits, separate mode axes | keep |
   | `TempDesiredLow` only human knob (5.7 KB) | ~0.8 KB: the only knob; `mc/RoomTempOffset` write-only/unusable; `mc` ≠ `rcc` offset; Raumaufschaltung off (owner action); boost overcomes the additive offset; Party/holiday unused. CORRECTION story, hypotheses 1/2, search log, "reference plan Task 3.1" → background |
2. [DONE] Note to the `doc/KNOWLEDGE.md` template; link the registers file. Background is NOT
   linked (K-1 forbids pointers from agent knowledge to background).
3. [DONE] Repoint references to moved decodes (YAML comments, plans, tests): grep for section names.

### Phase B: YAML comments (comment-only)
4. [DONE] Per block:
   | Lines | Content | Action |
   |---|---|---|
   | `:92-98`, `:115` | STATUS 2026-09-18 live ebusctl test | background |
   | `:31-36` | older config generation story | background |
   | `:60-75` | naming/slugify essay | background; keep 2-line force_update why |
   | `:895-899` | "ehp/Status was originally assumed…" | background |
   | `:893-913` | poll registration (≈ note copy) | 3 lines + note pointer |
   | `:1-6`, `:112`, `:134`, `:150`, `:427`, `:647`, `:829` | Phase 1/2/3 roadmap | condense, point to `plans/ebusd-pv-heating-optimization.md` |
5. [DONE] Fix yamllint comment warnings in touched blocks.

### Phase C: verify and close
6. [DONE] `yaml_semantic_equal.py master packages/heating_pv_boost.yaml` passes; `ci-local.sh`
   passes; `git ls-files --eol` clean; note ≤ 24 KB (target ≤ 12 KB). Push; CI green.
7. [TODO] Close: every removed fact has a home; delete this plan in the PR's last commit.

## Risks
- Owner-action facts (Raumaufschaltung) are current, not background, even though they came from an
  investigation.
- `plans/heating-baseline-and-phase2-prerequisites.md` and `plans/ebusd-*` may cite note sections:
  repoint them.
