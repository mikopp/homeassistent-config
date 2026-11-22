# <Maker> <Model>: access via <path>

> **TEMPLATE.** Copy as `access-<path>.md` (`access-ebusd.md`, `access-modbus.md`) only when
> `interface.md` is still over its cap (K-1.2) after the registers moved out; until then these sections are blocks under its
> `## Access`. See `README.md` in this folder.

Covers how this unit is reached over <path> and what it answers there; indexed by `interface.md`.
Only what the program's or integration's documentation omits, gets wrong or hides for this unit;
the generic part is a `software` References row with `Covers`. No entity ids.

## Path and config

- <bus or protocol> via <gateway or adapter> to <program or HA integration, version>; config
  source <catalog URL or file, which generation> [<REF>] [T<n>]
- Payload format on this setup (<plain or JSON>, field order) [T<n>]

## Addressing

- <bus address, circuit, unit id, register offset convention> [<REF> p.<n>] [T<n>]

## Polling and limits

- <how a value is refreshed: on request, priority, broadcast; block size, timeouts, rate> [T<n>]

## Writes

- <payload format, accepted values and resolution, read-back, prerequisites (enable register,
  access level)> [T<n>]
- Wiring a write needs on this setup: <broker bridge topics, adapter setting> [T<n>]

## Quirks of the software in between (as they affect this unit)

- <what the program or integration does differently for this unit than its docs say> [T<n>]
