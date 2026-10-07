# Store in a Box

A Couchbase demo: a store packed into a box (Edge Server and Couchbase Lite tablets) that sells offline, splits,
merges in any order and rejoins through Capella App Services. Start with `README.md`, then `docs/SPEC.md` (phased,
with acceptance criteria) and `docs/architecture/`.

The project is run with the foreman pattern: read `FOREMAN.md` before dispatching or reviewing work. Workstream
blueprints are in `docs/workstreams/`, decisions in `docs/decisions/`, and the shared contracts in `contracts/`, which
only the foreman changes. The owner merges PRs.

- No code yet. Build in the spec's phases, in order; Phase 0 has no AI.
- Use the spec's component names (Couchbase Lite, device-to-device sync, Couchbase Edge Server, Capella App Services).
- Never commit credentials, hostnames, IPs or local paths. Capella credentials come from `.env`.
- `node scripts/build-site.mjs` assembles the product page into `_site/`.
