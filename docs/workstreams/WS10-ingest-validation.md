# WS10: Ingest validation: schema pre-filter, the drop record, its surfacing, and the differential test

**Milestone:** M1  **Depends on:** WS1, WS4, WS5, WS6 merged; contracts 0.7.0 (CC11, #159) applied; #160 answered  **Label:** `ws:10-ingest-validation`  **Agent type:** ws-design
**Issues:** two, under one label and this blueprint: WS10a (Python, HQ, scripts; branch `ws10a/ingest-python`) and
WS10b (Swift; branch `ws10b/ingest-swift`, depends on WS10a merged). Design: `docs/architecture/servers-and-sync-trust.md`.

**Status (2026-10-13): WS10a dispatched.** The owner answered #160 and #161 (yes). CC11 is applied as contracts 0.7.0 (branch `foreman/cc11-contracts-0.7.0`, merged with WS10a's PR). WS10a is #175, WS10b is #176 (after WS10a merges).

The blueprint. The architect (`ws-architect`) writes it before any code is dispatched; the PR is judged against it.

## Scope

Decision [010](../decisions/010-reduce-only-valid-documents-log-every-drop.md): a node reduces only documents that
pass their collection's schema, drops the rest, records every drop, and never reports a conservation result computed
with drops as a plain `HOLDS`. This workstream builds it on both ports and surfaces it on both screens:

- **The Python reference (WS10a):** an `ingest` operation in `siab_ledger` that validates documents against
  `contracts/schemas/` with `jsonschema` and the validator's cross-field rules, returning the accepted documents and
  the drop records; the fixture runner applies it and compares `expected.drops`; a `report` subcommand for the
  differential test; the `scripts/ledger_diff.py` generator and compare.
- **HQ (WS10a):** the reconciler ingests what it reads before `reduce`, keeps a bounded drop log, validates what it
  writes before `upsert`, and the conservation API, the indicator and the panel say how many documents were dropped.
- **The tablet (WS10b):** a Swift validator mirroring the schemas; `CustodyStore` drops instead of skipping, keeps
  `local.drop_log`, publishes the drops; Diagnostics lists them and the status bar counts them; the fixture test reads
  raw JSON so fixtures can carry invalid documents; a differential test target; the CI wiring.

Left for later: a replicated drop record (Phase 2's device close may carry a count, #81); per-collection access on
the box (Edge Server 1.1.1, a WS3 follow-up, trust map Q3); HQ writing through the App Services endpoint (#93 option
b); signed documents; an HLC bound (trust map Q5); the catalog's skipped products beyond a log line.

## Files

Owned by this workstream:
- `src/siab_ledger/ingest.py` (new: `ingest`, `Drop`, the code mapping, the schema loader)
- `src/siab_ledger/fixtures.py`: the runner applies `ingest` and compares `drops`
- `src/siab_ledger/__main__.py`: the `report` subcommand
- `src/siab_ledger/__init__.py`: export `ingest`, `Drop`
- `scripts/ledger_diff.py` (new: `generate`, `compare`)
- `scripts/ledger_diff.sh` (new: the three steps on a Mac)
- `app/SIABCore/Sources/SIABCore/Validation.swift` (new: `DocumentCheck`, `Drop`, `DropCode`)
- `app/SIABCore/Sources/SIABCore/DropLog.swift` (new: `local.drop_log`)
- `app/SIABCore/Sources/SIABCore/CustodyStore.swift`: `all()` drops instead of skipping; `drops` publisher; the log
- `app/SIABCore/Sources/SIABCore/JSONValue.swift`: a `.double` case so a non-integer number is a value, not a parse failure
- `app/SIABCore/Tests/SIABCoreTests/LedgerFixtureTests.swift`: raw-JSON decode of `transactions` and `resolutions`; `drops` compared
- `app/SIABCore/Tests/SIABCoreTests/LedgerDifferentialTests.swift` (new)
- `app/SIABCore/Tests/SIABCoreTests/DocumentCheckTests.swift` (new: the `docs/<collection>/valid|invalid` corpus)
- `app/StoreInABox/Diagnostics/DiagnosticsView.swift`: the `Dropped documents` section
- `.github/workflows/ios.yml`: the differential step on the `community` leg
- `docs/architecture/servers-and-sync-trust.md`: section 6's table updated to "as built" when the PRs merge

Named edits in neighbours' code:
- `src/siab_hq/queries.py`: `TripData` gains `drops: list[Drop]`; `load` ingests `transactions` and `exceptions`.
- `src/siab_hq/reconcile.py`: `Status` gains `dropped: int`; `Hq` keeps the drop log; `_write_resolved`,
  `stage_hq_sale` and `run_once` validate before `upsert` (a failing write is `BadRequest`, never a document).
- `src/siab_hq/server.py`: `conservation_view` adds `dropped` and `drops`; `indicator()` wording; the panel's line.
- `ports/ledger.md`: the `ingest` operation and the `Drop` record; `report` in "Fixture runner".
- `ports/hq.md`: the `dropped` and `drops` fields, the indicator wording, `reconcile/status.dropped`.
- `app/StoreInABox/UI/Shared/StatusBar.swift`: `N dropped` when `N > 0` (owner decision Q2; omit if the owner says no).
- `app/StoreInABox/UI/Shared/CustodyStoring.swift`: the protocol gains `drops: AnyPublisher<[DropRecord], Never>`.
- `app/StoreInABox/App/AppModel.swift`: wires `drops` to the status bar.
- `app/README.md`: the Diagnostics paragraph names the new section.
- `docs/runbook/phase0.md`: acceptance line 6 passes only with `0 dropped` (one sentence; WS7 owns the file, this is
  the named edit).

## Interfaces

### The `Drop` record (owned here; shared by both ports)

```
Drop { id: string, collection: "transaction" | "exception", code: DropCode, detail: string }
DropCode, in priority order: malformed, wrong_type, version, missing_field, extra_field, invalid_value, rule
```

One `Drop` per `(collection, id)`: when several invalid bodies share an id, the record carries the smallest code in
that order. Keys beginning with `_` (`_id`, `_why`, `_invalid`) are fixture metadata and are ignored by both
validators. A valid body under an id that also has an invalid body is reduced; the drop still names the id.

**How a code is derived** (both ports, in this order; the first that fails is the code):
1. `malformed`: the body is not a JSON object.
2. `wrong_type`: `type` is absent or not the collection name.
3. `version`: `v` is absent or not `1`.
4. Then the collection schema. Python: every error from `jsonschema`'s `iter_errors`, mapped by the error's top-level
   `validator` keyword: `required` → `missing_field`; `additionalProperties` → `extra_field`; anything else (`type`,
   `enum`, `const`, `pattern`, `format`, `minItems`, `uniqueItems`, `minimum`) → `invalid_value`; the smallest code
   wins. **An `anyOf`/`oneOf` error takes the smallest code among its alternatives' errors** (`error.context`,
   recursively), which is the code of the alternative whose JSON type the value has: `exception.resolution` is `anyOf`
   [object, null], so a resolution object without `note` is `missing_field` (fixture `drop-resolution-missing-field`),
   and the same holds for `tender`, `price` and `chosen_txn`. `allOf`, `if`/`then`/`else` and `$ref` never appear as a
   top-level keyword in `jsonschema` (it reports the inner keyword). Swift: check missing required keys, then unknown
   keys, then every value (type, enum, pattern, nullability, the conditionals), at every nesting level, stopping at the
   first failing group; a value of the wrong JSON type inside a nullable object is judged against the object's keys.
   The expected code for each file of the `docs/` corpus is `INVALID_CODES` in `tests/ledger/test_ingest.py` (WS10a);
   `DocumentCheckTests` copies it. The derivation is written up in `ports/ledger.md`, "Ingest: how a drop's code is
   derived" (WS10a, #177).
5. `rule`: the cross-field checks of `scripts/check_contracts.py` (`CROSS_CHECKS`: `sku` is the SKU part of
   `unit_id`; `hlc` ends with `device`; an exception's `transactions` sorted and matching `branches`; `dispute_key`
   starts with `unit_id`; `resolution.hlc` ends with `resolution.by`). Both ports implement them; Python may import
   nothing from `scripts/` (copy the five checks into `ingest.py`, with a test that the two copies agree on the
   `docs/` corpus).

`detail` is the first failing check in words; it is logged and shown, never compared.

**The id template is part of rule 0** (foreman ruling 2026-10-13, reversing the same day's earlier one on #177 point 3, after the review gate on #181): `scripts/check_contracts.py` checks a fixture document's `_id` against the schema's `x-id-template`, and so does rule 0: a `transaction`'s `_id` must be `txn::<hlc>`, an `exception`'s `exc::<detected_by>::<unit_id>::<sha256_8 of its transactions>`; a document whose id disagrees is dropped with code `rule` (fixture `drop-id-mismatch`; 47 fixtures). Without it, a valid body under a wrong id is reduced and `exceptions_for` writes an exception that fails its own schema, which HQ's write-side check then refuses on every tick. Both ports implement it, Swift with CryptoKit for the `sha256_8`.

### Python (`ports/ledger.md` gains this)

```
ingest(docs, collection) -> Ingest(accepted: list[dict], drops: list[Drop])
  docs:       raw documents (dicts with _id), any order, duplicates allowed
  collection: "transaction" | "exception"
  accepted:   the bodies that pass, in input order; drops sorted by (collection, id)
reduce(...)     unchanged: its callers pass ingest(...).accepted
LedgerState     unchanged
Drop.to_json()  {"id", "collection", "code", "detail"}
```

Schemas are loaded from `contracts/schemas/` found as `default_fixtures_dir()` finds the fixtures (repository root
from the working directory, else the package's parents), overridable by `SIAB_CONTRACTS_DIR`. The `jsonschema`
dependency is already in `pyproject.toml`.

Fixture runner: `run()` ingests `transactions` and `resolutions`, reduces the accepted ones, and adds `"drops":
[{id, collection, code}]` (no `detail`) to the result; `first_difference` compares it. Every ordering of an
order-independent fixture must give the same `drops`.

CLI: `python -m siab_ledger report --sets DIR --out FILE`: for every `*.json` in `DIR` (the differential set format
below) writes one JSON object keyed by file name whose values are the `run()` result (`expected` shape plus `drops`),
canonical (`sort_keys=True, separators=(",", ":")`, `ensure_ascii=True`).

### HQ (`ports/hq.md` gains this)

- `GET /api/conservation` → `{ ..., "holds": bool, "dropped": N, "drops": [ { "id", "collection", "code", "detail",
  "source": "capella", "first_seen", "last_seen" }, ... ] }`; `drops` newest `last_seen` first, at most 50.
- `indicator(rows, dropped)`: `HOLDS · live` | `HOLDS · N dropped · live` | `K SKUs do not hold · live` | `K SKUs
  do not hold · N dropped · live`. Byte for byte.
- The conservation panel: under the table, `<p class="dropped">N documents dropped</p>` followed by one line per
  entry, `<collection> <id> · <code in words> · <last_seen>`, only when `N > 0`. Code words: `malformed`, `wrong
  type`, `newer schema: update the app` (for `version`), `missing field`, `unknown field`, `invalid value`, `rule`.
- `GET /api/reconcile/status` gains `"dropped": N` (the last run's).
- The drop log at HQ: in `Hq`, one entry per `(collection, id)`, at most 200, evicted by oldest `last_seen`; each new
  entry logged once at `WARNING` on logger `siab_hq.ingest` with id, collection, code, detail.
- Writes: `_write_resolved`, `stage_hq_sale` and the reconciler's exception upserts run `ingest([doc], collection)`
  first; a drop raises `BadRequest(f"HQ would write an invalid {collection}: {detail}")` (400) and writes nothing.
  (Q4; if the owner declines, the check is skipped and this bullet is struck.)
- `existing` ids in `run_once` keep coming from the raw read, dropped documents included, so HQ never overwrites a
  document it cannot read.

### Swift (`SIABCore`)

```swift
public enum DropCode: String, Codable { case malformed, wrongType = "wrong_type", version, missingField = "missing_field",
                                        extraField = "extra_field", invalidValue = "invalid_value", rule }
public struct Drop: Equatable, Codable { public var id: String; public var collection: String; public var code: DropCode; public var detail: String }
public struct DropRecord: Equatable, Codable { drop fields; public var source: String?; public var firstSeen: String; public var lastSeen: String }
public enum DocumentCheck {
  /// nil when the body passes its collection schema and the cross-field rules.
  public static func check(_ body: [String: JSONValue], id: String, collection: String) -> Drop?
  public static func ingest<T: Decodable>(_ bodies: [(id: String, body: [String: JSONValue])], collection: String, as: T.Type) -> (accepted: [T], drops: [Drop])
}
extension CustodyStore {
  public var drops: AnyPublisher<[DropRecord], Never>      // the log, newest first; published after every rebuild
  public var currentDrops: [DropRecord]
}
```

- `CustodyStore.all()` returns `(docs, drops)`; `rebuild()` runs `ingest` on `store.transaction` and
  `store.exception`, reduces the accepted, writes the drop log (`local.drop_log`, document id
  `<collection>::<id>`, fields as `DropRecord`, at most 200, evicted by oldest `lastSeen`), logs each new entry once
  (`os.Logger`, subsystem `com.example.storeinabox`, category `ledger`, level `.warning`), and publishes `drops`.
  `source`: `local` when the id's HLC device is this device; `box` when `SyncCoordinator` reported the id pulled
  (`documentsReplicated`; the coordinator exposes `pulledIDs: Set<String>` for this); else `peer`.
- `JSONValue` gains `case double(Double)` (decoded when `Int64` fails); `canonical` prints it as Python's `repr`
  would for the values the schemas allow (none: no schema has a non-integer number, so a double is always invalid and
  never reaches `canonical`; the case exists so the body parses and the code is `invalid_value`).
- `StoreProductCatalog.stored()` logs a skipped product once at `.warning` with the same words; no record.
- `LedgerFixtureTests.Fixture` decodes `transactions` and `resolutions` as `[[String: JSONValue]]` and runs
  `DocumentCheck.ingest` before `Ledger.reduce`; `run()` adds `drops` to the result; the `expected` compare covers it.
- `LedgerDifferentialTests`: when `SIAB_DIFF_SETS` is set, reads every `*.json` set, produces the same report as
  `siab_ledger report` and writes it to `SIAB_DIFF_OUT` (canonical JSON, byte-compatible with Python's); skipped
  otherwise.
- Diagnostics: a `Dropped documents` section after `Counts`: `dropped: N documents` (accessibility id `dropped`),
  then up to 10 rows `<collection> <id>` / `<code in words> · <source> · <HH:mm>`, newest first. The code words are
  the HQ list above, so both screens say the same thing.
- Status bar (Q2): a fourth label `N dropped`, amber, only when `N > 0`; tapping it opens Diagnostics.

### The differential set format (owned here)

`DIR/<fixture name>-<k>.json`: `{ "name", "trip", "box", "store", "detector", "inventory", "transactions", "resolutions" }` (`detector` is the fixture's `expected.exceptions.detector`, which `exceptions_for` needs), the
ledger fixture without `expected`, `description` or `order_independent`. Documents may be invalid. `scripts/ledger_diff.py
generate --seed N --out DIR [--per-fixture K]` writes, per fixture: `-0` the fixture's order, `-1` reversed, `-2..`
shuffled with duplicates (a third of the transactions and the first resolution delivered twice), and from `-K/2` on
corrupted: for each of a random 20% of the documents one mutation from this list: remove a required key; add a key
`note`; set `v` to 2; set `kind` to `transfer` or `status` to `pending`; set `sku` to another SKU in the set; replace
`price.cents` with `12.5`; set `type` to another collection name; set `prev_txn` to `txn::bad`; set `resolution.hlc`
to end in `tablet-a`; set `to_custodian` to `customer` on a check_out. Seeded by `f"{seed}/{name}/{k}"`.
`compare A.json B.json` prints `PASS <set>` or `FAIL <set>: <first difference>` per set in file-name order (the
fixture runners' `first_difference`) and exits 1 on any failure.

## Contract changes

**CC11, contracts 0.7.0** (a changed reducer rule, so a minor bump; decision 010). Filed as `contract-change`
issue #159; only the foreman applies it.

1. **`contracts/fixtures/README.md`**, a new rule 0 before rule 1, under "`ledger/<scenario>.json`":

   > 0. **Ingest.** The reducer's input is documents that pass their collection's schema (`schemas/store/`) and the
   > cross-field rules `scripts/check_contracts.py` checks. A node validates every `transaction` and `exception` it
   > reads before rule 1 runs; a document that fails is *dropped*: not reduced, not an error, and recorded as a drop
   > `{id, collection, code}`, where `code` is the first of `malformed` (not a JSON object), `wrong_type` (`type` is
   > not the collection), `version` (`v` is not 1), `missing_field`, `extra_field`, `invalid_value` (a value fails its
   > type, enum, pattern or a conditional), `rule` (a cross-field rule). Validation precedes rule 5's dedupe: when
   > several bodies share an id, only the valid ones are compared, and one drop names the id whatever the number of
   > invalid bodies, with the smallest code. Keys beginning with `_` are fixture metadata and are ignored. A drop
   > changes no row directly (the rows are computed over what remains, dangling roots and all), and a report computed
   > with drops is never a plain `HOLDS`: it carries the count.

   And under "What `expected` holds": `drops`: every drop, `{id, collection, code}`, sorted by `collection` then `id`;
   `[]` when none. And in the format paragraph: a document in `transactions` or `resolutions` may carry
   `"_invalid": "<why>"`; the validator checks that it fails its schema, that every other one passes, and that the
   `_invalid` ids are exactly `expected.drops`' ids. A duplicate `_id` in `transactions` is allowed only when all but
   one of its bodies are `_invalid`.
2. **`contracts/schemas/fixtures/ledger.schema.json`**: `expected.drops` required, `type: array`, items
   `{ "id": string, "collection": enum ["transaction", "exception"], "code": enum [the seven] }`, `additionalProperties:
   false`. Every existing fixture gains `"drops": []`.
3. **`scripts/check_contracts.py`**: `STRIPPED` gains `_invalid`; in `check_ledger`, a transaction or resolution with
   `_invalid` must fail `doc_errors` (report `should fail validation (...) but passes` otherwise) and is excluded from
   the "is resolved" and "on trip" checks; the set of `_invalid` ids must equal `{d["id"] for d in expected["drops"]}`;
   duplicate ids are reported unless all but one copy carry `_invalid`.
4. **`ports/ledger.md`**: the `ingest` operation (Interfaces above) and "Fixture runner" gains the `drops` comparison
   and `report`.
5. **`CHANGELOG.md`**: `- 0.7.0 (<date>): a node reduces only schema-valid documents and records every drop (rule 0;
   #96, #104 item 4, CC11 #159, decision 010): `expected.drops` in every ledger fixture, documents marked `_invalid`,
   the seven drop codes. Fixtures `drop-transaction-missing-field`, `drop-resolution-missing-field`,
   `drop-extra-field-same-id`, `drop-newer-version`, `drop-unknown-kind`, `drop-rule-sku-mismatch`,
   `drop-and-untraced`. A changed rule, so a minor bump.` `VERSION` 0.7.0.
6. **The fixtures.** All `order_independent: true`, `trip` `trip-2026-10-18-riverfest`, `box` `box-07`, `store`
   `store-richmond`, detector `tablet-a`. P, A, B are the three transactions of `double-scan.json` (the pack
   `txn::1792328410000-0000-tablet-a` to `alloc::1792328400000-0000-tablet-a`; tablet-a's take
   `txn::1792328510000-0000-tablet-a` to `alloc::1792328500000-0000-tablet-a`; tablet-b's take
   `txn::1792328511000-0000-tablet-b`). "Expected as held by the box" means: `units` `{#001: {sku, holder box-07,
   allocation alloc::…400000-…, state held, last_txn P}}`, `counts` `[{box-07, JKT-RAIN-M-BLU, 1}]`,
   `allocation_counts` `{alloc::1792328400000-0000-tablet-a: 1}`, `forks []`, `exceptions {detector tablet-a, docs
   []}`, `venue_only` one row `{sku JKT-RAIN-M-BLU, opening null, received null, left_store 1, untraced 0,
   returned_to_store 0, store_on_hand null, in_custody {box-07: 1}, sold 0, disputed 0, holds true}`.
   - **`drop-transaction-missing-field`** (#96 case 3; E1). `inventory`: `[inventory::store-richmond::JKT-RAIN-M-BLU,
     opening 12, received 0]` as in `oversell-hq`. `transactions`: P; A without the `device_clock` key, `"_invalid":
     "device_clock is required"`. Expected: as held by the box; `with_inventory` one row `{opening 12, received 0,
     left_store 1, untraced 0, returned 0, store_on_hand 11, in_custody {box-07: 1}, sold 0, disputed 0, holds true}`;
     `drops [{A, transaction, missing_field}]`. Description: "The take lacks a required field: dropped, counted, and
     the unit is where the pack left it."
   - **`drop-resolution-missing-field`** (#96 case 2; E2). `transactions`: P, A, B. `resolutions`: one document
     `exc::hq::JKT-RAIN-M-BLU#001::111c7a4e` (the double-scan exception as HQ's copy: `box null`, `detected_by hq`,
     `detected_at 1792329000000-0000-hq`, `status resolved`, `resolution {by hq, at 2026-10-18T13:20:00Z, hlc
     1792329600000-0000-hq, chosen_txn A}` with **no `note`**), `"_invalid": "resolution.note is required"`.
     Expected: exactly `double-scan.json`'s `expected` (the fork open, the unit disputed, tablet-a's `double_scan`
     document) plus `drops [{exc::hq::JKT-RAIN-M-BLU#001::111c7a4e, exception, missing_field}]`. Description: "HQ's
     resolution lacks a field: it does not count, on either port; the fork stays open."
   - **`drop-extra-field-same-id`** (#96 case 1; E3). `transactions`: P, A, and a second body with A's `_id` equal to
     A plus `"note": "edited"`, `"_invalid": "note is not a transaction field"`. Expected: `units {#001: holder
     tablet-a, allocation alloc::1792328500000-0000-tablet-a, held, last_txn A}`, `counts [{tablet-a, JKT-RAIN-M-BLU,
     1}]`, `allocation_counts {alloc::…400000: 0, alloc::…500000: 1}`, no forks, no docs, `venue_only {left_store 1,
     untraced 0, returned 0, in_custody {tablet-a: 1}, sold 0, disputed 0, holds true}`, `drops [{A, transaction,
     extra_field}]`. Description: "Two bodies under one id; the one with a field the schema does not know is
     dropped and the valid one is reduced, so rule 5 never compares an invalid body."
   - **`drop-newer-version`** (E7). `transactions`: P; A with `"v": 2`, `"_invalid": "v is not 1"`. Expected: as held
     by the box, `drops [{A, transaction, version}]`. Description: "A document from a newer schema is dropped with the
     one code an operator can act on."
   - **`drop-unknown-kind`** (#104 item 4; E4). `transactions`: P; A with `"kind": "transfer"`, `"_invalid": "transfer
     is not a kind"`. Expected: as held by the box, `drops [{A, transaction, invalid_value}]`.
   - **`drop-rule-sku-mismatch`** (the cross-field rule). `transactions`: P; A with `"sku": "JKT-RAIN-L-BLU"`,
     `"_invalid": "sku is not the SKU part of unit_id"`. Expected: as held by the box, `drops [{A, transaction,
     rule}]`.
   - **`drop-and-untraced`** (never a plain HOLDS, and a failing row beside a drop). `transactions`: the two of
     `untraced-unit.json` (the pack of `SOC-WOOL-M#001`, `txn::1792328431000-0000-tablet-a`; the check-in of
     `SOC-WOOL-M#009` from `unknown`, `txn::1792334100000-0000-tablet-b`) plus a third, `txn::1792334200000-0000-tablet-b`,
     a `check_out` of `SOC-WOOL-M#001` from box-07 to tablet-b, `prev_txn` the pack, `from_allocation
     alloc::1792328401000-0000-tablet-a`, `to_allocation alloc::1792334150000-0000-tablet-b`, `hlc
     1792334200000-0000-tablet-b`, `device_clock 2026-10-18T14:36:40Z`, with the `tender` key removed, `"_invalid":
     "tender is required"`; `inventory` as in `untraced-unit.json`. Expected: exactly `untraced-unit.json`'s `expected` (the pack holds, #009 untraced on the
     box, the `unexpected_check_in` document `exc::tablet-a::SOC-WOOL-M#009::5c1dfb92`, the `SOC-WOOL-M` row with
     `untraced 1`, `holds false`) plus `drops [{txn::1792334200000-0000-tablet-b, transaction, missing_field}]`.
     Description: "A row that does not hold and a dropped document: both are reported, neither hides the other."

## Exit criteria

WS10a (Python, HQ, scripts):
- [ ] `tests/ledger/test_ingest.py::test_docs_corpus_agrees_with_check_contracts`: every `contracts/fixtures/docs/*/valid/*.json`
      is accepted and every `invalid/*.json` dropped by `ingest`, with the code the mapping gives.
- [ ] `tests/ledger/test_ingest.py::test_code_priority_and_one_drop_per_id`: a body with a missing key and an extra key
      gives `missing_field`; two invalid bodies under one id give one drop with the smaller code; `_`-keys ignored.
- [ ] `tests/ledger/test_fixtures.py::test_fixture_passes[drop-*]`: the seven CC11 fixtures pass, in every ordering, and
      `python -m siab_ledger check` prints `PASS` for all 46.
- [ ] `tests/ledger/test_ingest.py::test_keyerror_is_gone`: the #96 case-3 document (a transaction missing a required
      field) no longer raises from `reduce`'s callers: `ingest` drops it.
- [ ] `tests/hq/test_drops.py::test_conservation_reports_drops`: `SIAB_HQ_FAKE=drop-transaction-missing-field` gives
      `dropped: 1`, one `drops` entry with `code: missing_field`, `source: capella`, and the rendered panel carries
      `HOLDS · 1 dropped · live` and `missing field`; `drop-and-untraced` renders `1 SKUs do not hold · 1 dropped · live`.
- [ ] `tests/hq/test_drops.py::test_reconciler_survives_invalid_rows`: three virtual-time ticks over a fake holding an
      invalid transaction: no `last_error`, `dropped: 1` every tick, the log holds one entry with `last_seen` advancing.
- [ ] `tests/hq/test_drops.py::test_hq_refuses_to_write_an_invalid_document`: a resolve whose resulting document would
      fail the schema is `400` and `FakeCapella.calls` has no upsert (Q4).
- [ ] `tests/hq/test_drops.py::test_drop_log_is_bounded`: 250 invalid ids give 200 entries, the oldest evicted.
- [ ] `tests/scripts/test_ledger_diff.py`: `generate` is deterministic per seed and every set validates against the
      set format; `compare` of a report with itself passes and of two differing reports prints the first difference
      and exits 1; `python -m siab_ledger report` over a generated directory produces canonical JSON.
- [ ] `python -m siab_ledger report --sets <generated> --out r.json && scripts/ledger_diff.py compare r.json r.json`
      exits 0.
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

WS10b (Swift):
- [ ] `DocumentCheckTests.testDocsCorpus`: every `contracts/fixtures/docs/*/valid` accepted, every `invalid` dropped,
      with the code Python's mapping gives for each (the expected codes are listed in the test, one per file).
- [ ] `LedgerFixtureTests.testEveryFixturePasses`: all 46 fixtures, `drops` compared, report lines match
      `python -m siab_ledger check` line for line.
- [ ] `CustodyStoreTests.testInvalidDocumentIsDroppedNotSkipped`: a body with `kind: "transfer"` saved into
      `store.transaction` of a real local database gives, after `rebuild()`, one `DropRecord` (`invalid_value`,
      `source: peer`), a `local.drop_log` document, `state.transactions` without it, and `currentDrops` published.
- [ ] `CustodyStoreTests.testDropLogIsBoundedAndKeyed`: 250 invalid documents give 200 log entries; re-saving one
      updates `lastSeen` only.
- [ ] `CustodyStoreTests.testVersionTwoIsDroppedAsVersion`: a `v: 2` transaction gives `code: version`.
- [ ] `JSONValueTests.testDoubleParsesAndIsInvalidValue`: `{"cents": 12.5}` parses; the sale is dropped `invalid_value`.
- [ ] `LedgerDifferentialTests`: with `SIAB_DIFF_SETS` set, writes the report; `.github/workflows/ios.yml`'s
      `community` leg runs generate (seed = `github.run_number`), both reports and `compare`, green on the PR.
- [ ] `[macos-xcode]` Two simulators, EE: a `v: 2` transaction saved on one (a test hook or `Movement check` variant)
      shows `dropped: 1 documents` on the other's Diagnostics within 5 s, with `newer schema: update the app` and
      `source peer`; the status bar shows `1 dropped`. Screen capture in the PR.
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

## Owner decisions
- #160: the drop record, the local-only log, `expected.drops`, the seven codes and the indicator wording
  (recommend: as designed; **blocks dispatch: yes**, CC11 #159 depends on it).
- #161: the clerk-facing status bar shows `N dropped` when `N > 0` (recommend: yes; blocks dispatch: no; the
  default applies if unanswered).
- Q4, folded into #160: HQ validates what it writes (recommend: yes; blocks dispatch: no).
- #163 (not WS10's; a WS3 follow-up): Edge Server 1.1.1 per-collection access control to close #50 on the box
  (recommend: yes, after Stage A; blocks dispatch: no).

## Verification plan
- The `v: 2` document from a peer appearing as a drop on the other tablet, and HQ's indicator reading `1 dropped`
  after the box pushes it: agent with `macos-xcode` for the two-simulator half; agent with `box` and `capella` for the
  HQ half (push an invalid transaction through the box, read `/api/conservation`). The implementer files both as
  `needs-verification`.
- A dropped document's `source: box` attribution on a real device (the pull listener fires before the rebuild):
  agent with `box` and a device, or the rehearsal (#124).
- The status bar's `N dropped` label from the back of a room: owner, with #132.
- The differential test's run time on the macOS runner stays under 3 minutes: the implementer records it in the PR.

## Tasks

WS10a, `ws-design`, branch `ws10a/ingest-python`:
1. `[any]` `ingest.py`: the loader, the code mapping, the five cross-field checks, `Drop`. Accept: the two
   `test_ingest.py` criteria.
2. `[any]` The fixture runner and `report`; `ports/ledger.md`. Accept: all 46 fixtures `PASS`; `report` canonical.
3. `[any]` HQ: `queries.load` ingests; the log on `Hq`; the write-side check; the API, indicator and panel;
   `ports/hq.md`. Accept: the four `test_drops.py` criteria.
4. `[any]` `scripts/ledger_diff.py` and `.sh`. Accept: `test_ledger_diff.py`.
5. `[any]` **PR.** One PR, `Closes #175`; `needs-verification` issues filed and linked from "Not verified".
   Expected size: about 550 lines of code (tests and fixtures not counted).

WS10b, `ws-design`, branch `ws10b/ingest-swift`, after WS10a merges:
6. `[macos-xcode]` `Validation.swift` and `JSONValue.double`; `DocumentCheckTests` over the `docs/` corpus. Accept:
   `testDocsCorpus` with the codes Python gives (run `python -m siab_ledger` on the corpus to list them).
7. `[macos-xcode]` `CustodyStore.all()` drops; `DropLog.swift`; `drops` publisher; the coordinator's `pulledIDs`;
   `LedgerFixtureTests` on raw JSON. Accept: the `CustodyStoreTests` criteria and all 46 fixtures.
8. `[macos-xcode]` Diagnostics section, status bar label, `CustodyStoring.drops`, `AppModel`. Accept: the
   two-simulator criterion.
9. `[macos-xcode]` `LedgerDifferentialTests` and the CI step. Accept: green on the PR with the step's log showing
   `PASS` per set.
10. `[any]` **PR.** One PR, `Closes #176`. Expected size: about 650 lines of code.

## Rules
- Code against `contracts/` and `ports/`; fake your neighbours.
- Deadline, timeout and retry tests use virtual time (a fake clock or a virtual-time event loop), not wall-clock
  sleeps: wall-clock races pass locally and flake on CI.
- Generated code is regenerated by its script, never edited by hand.
- Do not edit `contracts/` -- open a `contract-change` issue for the foreman.
- Stay inside the Files list above; an edit you need outside it gets a `for-foreman` issue first.
- Work in your own git worktree/branch `ws<N>/<topic>`; one PR per issue; CI must be green.
- Notes, questions and decision requests for the foreman: file an issue with the `for-foreman` label (see FOREMAN.md).
  Do not leave them only in PR comments.
