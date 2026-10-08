# Contracts

The shared contracts of Store in a Box: one JSON Schema per collection and the golden fixtures every implementation
must pass. The tablets (Swift), the box and Capella tooling (Python) and the sync functions (JavaScript) are written in
different languages, so the fixtures, not any one language's types, are the source of truth. Only the foreman changes
this directory; a workstream that needs a change files a `contract-change` issue (`FOREMAN.md`, "Contract changes").

```
contracts/
  VERSION                         semver of the contracts as a whole
  CHANGELOG.md                    one line per version
  schemas/
    common.schema.json            shared $defs: ids, hlc, money
    store/<collection>.schema.json    product, inventory, trip, allocation, transaction, exception
    fixtures/                     the formats of the fixture files themselves
      custodians.schema.json, ledger.schema.json, sync-case.schema.json
  fixtures/                       see fixtures/README.md
    docs/<collection>/valid|invalid/*.json
    seed/products.json, inventory.json, trips.json, custodians.json
    ledger/<scenario>.json
    sync/<case>.json
```

Check everything with `python3 scripts/check_contracts.py` from the repository root (`-v` also shows why each
invalid fixture fails; `--self-test` checks the validator itself). It needs only `jsonschema >= 4.18`. CI runs it on
every PR.

## Conventions

- JSON Schema draft 2020-12. `$id` is `siab://contracts/store/<collection>.schema.json`; references are relative
  (`../common.schema.json#/$defs/sku`). `title` is the collection name.
- `additionalProperties: false` at the top level and in every nested object.
- Every document has `"v": 1` and `"type": "<collection>"`.
- Document ids are not in the body. Each schema's `x-id-template` gives the id (`product::{sku}`;
  `{sha256_8:transactions}` is the first 8 hex characters of sha256 over the ids, sorted and joined by `|`).
  Fixtures carry the id as `_id`, and the validator strips `_id` and `_why` before validating.
- Timestamps are RFC 3339 (`format: date-time`), dates are `format: date`.
- Money is integer cents, `{ "cents": 12900, "currency": "USD" }` (decision 003).
- Rules a schema cannot express (a transaction's `sku` is the SKU part of its `unit_id`; an `hlc` ends with its
  writer's device id; an exception's `transactions` are sorted and match its `branches`) are checked by the validator.

## Versioning

`VERSION` is semver. An additive, optional field bumps the patch. A new required field, a removed field or a changed
enum bumps the minor while we are before 1.0, and gets a decision note in `docs/decisions/`. A changed reducer rule
(one that changes `expected` for some input, whether or not a fixture holds that input) bumps the minor too, with a
decision note; a wording correction that changes no `expected`, or new fixtures alone, bumps the patch. Every bump
is one line in `CHANGELOG.md`. Workstreams rebase onto the new version.

Seed and policy documents in the live Capella bucket are derived from `fixtures/seed/`. Editing one there is a contract
change, and a re-seed overwrites the live edit, so diff first (`siab-capella seed --diff`).
