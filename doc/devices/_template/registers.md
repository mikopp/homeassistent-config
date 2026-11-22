# <Maker> <Model>: registers <area>

> **TEMPLATE.** Copy as `registers-<area>.md` (a circuit or an address range) only when
> `interface.md` would pass its cap (K-1.2); the first split; until then the table stays in its `## Registers`.
> See `README.md` in this folder.

Covers the register definitions of <area> (<circuit or address range>); indexed by `interface.md`.
What the unit does with them: `behaviour.md`. No entity ids.

| ID | Register / path | Decode (type, scale, unit) | Values / range | Access | Evidence |
|---|---|---|---|---|---|
| <PFX>-<n> | <name or address> | <fields, type, scale, unit> | <range; enum values, both forms if the path delivers both> | r / w / rw | [<REF>] [T<n>] |
