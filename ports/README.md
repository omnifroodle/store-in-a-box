# Ports

`ports/` holds the language-neutral interfaces one workstream exposes to another: what each side may rely on, so
both can be built and tested against fakes before the other exists.

- [`capella.md`](capella.md): the `CapellaGateway` protocol and `FakeCapella` (WS2), and the `.env` variable names.
- [`box-agent.md`](box-agent.md): the box agent's HTTP API (status, uplink cut and restore, byte counter) and the
  pairing payload each device scans (WS3).
