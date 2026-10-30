# Design docs

One design doc per package: `doc/design/<package>.md`, same basename as `packages/<package>.yaml`.

A design doc explains **what the package does and why it is built that way**, for the owner and
for agents: the behaviour, the design choices, how it coordinates with other packages, what can be
tuned, and the trade-offs that were accepted. It describes the current (or, while not yet built,
the agreed) design.

It is not:

- an implementation plan — work steps, migrations and test lists go in `plans/`;
- package notes — hardware quirks and coding rules for agents go in `packages/notes/<package>.md`.

When a package's behaviour or design changes, change its design doc in the same commit.

## Index

| Package | Design doc | Status |
|---------|------------|--------|
| `hrds_dehumidifier.yaml` | [`hrds_dehumidifier.md`](hrds_dehumidifier.md) | designed, not implemented |
