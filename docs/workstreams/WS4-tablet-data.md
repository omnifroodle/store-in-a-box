# WS4: Tablet data layer: Couchbase Lite, the Swift ledger, replication to the box and device-to-device sync

**Milestone:** M1  **Depends on:** WS1 (reducer rules and fixtures), contracts v0.4.0 (CC3, CC4, CC5, CC6, CC7, CC8); WS3 for the live tasks  **Label:** `ws:4-tablet-data`  **Agent type:** ws-design
**Issue:** #15

The blueprint. The architect (`ws-architect`) writes it before any code is dispatched; the PR is judged against it.

## Scope

Everything under the screens of the POS app: the Xcode project and app shell, a Swift package `SIABCore` holding
the document models, the Swift port of the custody ledger (same rules, same fixtures as WS1), the hybrid logical
clock, the Couchbase Lite database with the `store` collections and a non-replicated `local` scope for derived
state, the three write operations (check out, check in, sell) each as one `inBatch`, the replicator to the box
(Couchbase Edge Server) configured from the pairing QR, the **Multipeer Replicator** mesh between tablets and the
phone (device-to-device sync), and a single diagnostic screen showing device identity, box and peer state and the
live counts. WS6 builds the clerk-facing screens on top of this.

Left for later: all clerk UX (WS6), vector search and the upsell advisor (Phase 1), customers, allowances and
encryption at rest (Phase 1), peer authentication beyond "any peer in the group" (Phase 1 hardening, see
Interfaces), two-level splits on stage (the ledger already handles depth; the phone build is exercised in Phase 1),
blobs.

## Files

Owned by this workstream:
- `app/` (new: `app/StoreInABox.xcodeproj/`, `app/StoreInABox/` the app target with `App/`, `Diagnostics/`,
  `Resources/` including `Info.plist`; `app/SIABCore/` a local Swift package with `Sources/SIABCore/` and
  `Tests/SIABCoreTests/`; `app/README.md`)
- `.github/workflows/ios.yml` (new: the macOS CI job; see Exit criteria)

Named edits in neighbours' code:
- `ports/README.md`: append one line pointing at `ports/ledger.md` as implemented by `SIABCore`.

WS6 later owns `app/StoreInABox/UI/` and makes named edits in `app/StoreInABox/App/`; keep the app target's
composition root (`App/AppModel.swift`) small so WS6 can add screens without touching `SIABCore`.

## Interfaces

**Platform**: iOS 17+, Swift 5.10+, SwiftUI, Couchbase Lite Swift 4.x (the version that ships `MultipeerReplicator`
on the owner's devices; 4.1+ if an Android device ever joins), via Swift Package Manager or CocoaPods as the
Couchbase docs for that version require. Vector Search extension is not added in Phase 0.

**Collections on the device** (same names as the cluster, CC1): scope `store`: `product`, `trip`, `allocation`,
`transaction`, `exception` (all replicated); scope `local`: `unit_state` (derived, one document per unit, rebuilt
by the reducer), `device` (this device's identity and pairing; never replicated). Nothing in `local` is ever
added to a replicator.

**`SIABCore` public API** (names fixed; bodies are the implementer's):
```swift
public struct HLC: Comparable, Codable { public let string: String }           // "<ms13>-<hex4>-<device>"
public protocol Clock { func nowMs() -> Int64 }                                 // injected; tests fake it
public enum Custodian { static let store = "store-richmond", customer = "customer" }

public struct Transaction: Codable, Identifiable { ... }                         // mirrors transaction.schema.json
public struct Allocation: Codable, Identifiable { ... }
public struct ExceptionDoc: Codable, Identifiable { ... }
public struct Product: Codable, Identifiable { ... }
public struct Trip: Codable, Identifiable { ... }

public enum Ledger {
  public static func reduce(transactions: [Transaction], resolutions: [ExceptionDoc], store: String) -> LedgerState
  // store: the store custodian id (Custodian.store in Phase 0; each fixture carries it as `store`). Rule 1 needs it
  // to tell a store root from a blind movement; the reducer is pure and reads no registry (#59, ports/ledger.md).
  public static func exceptions(for state: LedgerState, detector: String, trip: String, box: String?) -> [ExceptionDoc]
  public static func conservation(state: LedgerState, store: String, inventory: [Inventory]?) -> [ConservationRow]
  // ConservationRow mirrors WS1's row (sku, opening_on_hand, received, left_store, untraced, returned_to_store,
  // store_on_hand, in_custody, sold, disputed, holds); venue-side callers pass inventory nil. CC5 (#29).
}
public struct LedgerState { units: [String: UnitState]; counts: [CustodianSKU: Int]; allocationCounts: [String: Int]; forks: [Fork] }

public final class CustodyStore {                                              // the only writer to `store.*`
  public init(database: Database, identity: DeviceIdentity, clock: Clock)
  public func checkOut(unit: UnitID, from: String, to: String, actingFor box: String?) throws -> Transaction
  public func checkIn(unit: UnitID) throws -> Transaction                         // to the parent of this device's allocation
  public func sell(unit: UnitID, tender: Tender, price: Money) throws -> Transaction
  public func detectAndWriteExceptions() throws -> [ExceptionDoc]                 // idempotent, uses Ledger.exceptions
  public var state: AnyPublisher<LedgerState, Never>                              // recomputed on any store.transaction / store.exception change
}

public struct PairingPayload: Codable { v, box, trip, device, edge_url, user, password, cert_sha256, peer_group }  // WS3 owns production
public final class SyncCoordinator: ObservableObject {
  public init(database: Database, pairing: PairingPayload, identity: TLSIdentityProvider)
  @Published public var box: BoxLink          // .connected(url) | .offline(lastSeen) | .error(String) ; replicator status + doc counters
  @Published public var peers: [PeerLink]     // id, last seen, state, from the MultipeerReplicator
  public func start(); public func stop()
}
```

**Write rules** (the device-side half of the ledger contract; CC3 has the document fields):
- Every write is one `inBatch`: the `transaction`, the `allocation` it opens or closes (if any), and nothing else.
- `checkOut(unit:from:to:actingFor:)`: `to` is this device, or this device's box when `actingFor` is set (pack mode:
  the tablet scans units out of the store onto the box). `prev_txn` is the id of the latest movement this device
  knows for the unit (from `local.unit_state`), or `null` when this device has no record of the unit: the first
  scan out of the store (pack mode, `from` the store), or a *blind take* off the box before the pack replicated
  (`from` the custodian being scanned from, the box in Phase 0; never `unknown`, which is a check-in's source
  only). A blind take is an ordinary write with `from_allocation: null`: `checkOut` never waits for replication
  and never refuses for lack of a record. The ledger (WS1 rule 1, CC6 #33) links it under the pack once the pack
  arrives, and a double take forks there; nothing on the device special-cases it.
  Opens an `allocation` for `(to, sku, parent)` if none is `active`, else reuses it; sets `to_allocation`.
- `checkIn(unit:)`: `from` is the unit's holder as this device knows it from `local.unit_state` (normally this
  device; it may be another custodian), `to` is the custodian of the parent of that holder's allocation and
  `to_allocation` that parent allocation (in Phase 0 the parent is always the box's allocation; the store root is
  never a check-in target), `prev_txn` the latest movement this device knows. Never fails because
  the record disagrees: a unit with no local record is written with `from: "unknown"`, `prev_txn: null`,
  `to: this device's box`, `to_allocation: null` (WS1 rule 6 turns both cases into an `unexpected_check_in`
  exception; the movement itself stands). Closes this device's allocation when its derived count reaches zero.
- `sell(unit:tender:price:)`: `from` is the unit's current holder as this device knows it (this device, or the
  box when selling off the table), `to` is `customer`, `to_allocation` null, `tender` and `price` set. With no
  record of the unit: `from` the box, `prev_txn: null`, `from_allocation: null` (a blind sale; the same ledger
  rule links it under the pack).
- `detectAndWriteExceptions()` writes only documents whose id does not already exist locally.
- HLC: `hlc_now` on every write; `hlc_receive` on every pulled transaction (keeps the local clock ahead of what it
  has seen). `device_clock` is the wall clock; `box_clock` is `null` in Phase 0.

**Replication to the box**: one `Replicator`, continuous, push and pull, the five `store` collections, target
`pairing.edge_url`, basic auth `pairing.user`/`pairing.password`, `pinnedServerCertificate` when `cert_sha256` is
set (fetch `/cert.pem` from the box agent at pairing and verify the fingerprint). Checkpoints are the replicator's
own. Nothing waits on it.

**Device-to-device**: one `MultipeerReplicator` with `peerGroupID = pairing.peer_group`, the five `store`
collections, both transports (Wi-Fi via DNS-SD, Bluetooth LE where the device has it), a self-signed
`TLSIdentity` per device created at first launch and kept in the keychain, and an authenticator that accepts any
peer presenting a certificate (Phase 0; Phase 1 pins the box-vended CA). `Info.plist`: `NSBonjourServices`
`_couchbaseP2P._tcp`, `NSLocalNetworkUsageDescription`, `NSBluetoothAlwaysUsageDescription`, plus
`NSCameraUsageDescription` for WS6.

**Ledger fixtures in Swift**: `SIABCoreTests/LedgerFixtureTests` reads every file in `contracts/fixtures/ledger/`
through a folder reference to the repo's `contracts/fixtures/ledger` (no copies), decodes, runs `Ledger.reduce`
and compares to `expected`; for `order_independent` fixtures it also runs a seeded shuffle.

**Diagnostics screen** (the only UI here; WS6 keeps it behind a gear icon): device id, trip, box link state and
document counters, peers with last-seen, the `counts` table from `LedgerState`, a "Pair" button that scans the
box's pairing QR (camera; WS6 reuses the scanner view) and a "Rebuild derived state" button.

## Contract changes

- CC3 (#4), CC4 (#5), CC5 (#29, the conservation row), CC6 (#33, blind movements: rules 1 and 2 and three
  fixtures, which the Swift port must pass like every other), CC7 (#44, contracts 0.3.1: two dangling roots naming
  the same missing `prev_txn` are a fork, and four more blind-movement fixtures, one of them a blind `sale`, which
  is what `sell` writes with no record). No new change of its own. If the Swift port needs a fixture the Python
  one did not (an edge case the port hits), file a `contract-change` for the fixture rather than diverging.
- CC8 (#70, contracts 0.4.0): resolutions bind to the branches they were written for, and `returned_to_store` counts every
  unit the store holds; the Swift port implements the same text (README rules 2, 3, 7) and passes the six new fixtures.

## Exit criteria

- [ ] `xcodebuild test -project app/StoreInABox.xcodeproj -scheme SIABCore -destination 'platform=iOS Simulator,name=iPhone 16'`
      passes, including `LedgerFixtureTests` over every fixture in `contracts/fixtures/ledger/` (the report lists
      one PASS line per fixture, matching `python -m siab_ledger check` line for line).
- [ ] `SIABCoreTests` includes `testEverySaleIsOneBatch` (a failure injected after the transaction write leaves no
      transaction and no allocation change), `testCheckInNeverFailsOnDisagreement`, `testHLCAdvancesOnReceive`,
      `testLocalScopeIsNotInAnyReplicatorConfig`, `testPairingPayloadDecodesPortExample` (the JSON example in
      `ports/box-agent.md`), `testDetectAndWriteExceptionsIsIdempotent`, `testCheckOutWithoutRecordIsABlindTake`
      (a `checkOut` from the box of a unit with no `local.unit_state` document returns without waiting and writes
      `prev_txn: null`, `from_custodian` the box, `from_allocation: null`; after the pack transaction is inserted
      as if pulled, `state` shows the unit held by this device, `forks` empty and `detectAndWriteExceptions()`
      writes nothing).
- [ ] `.github/workflows/ios.yml` runs the command above on `macos-latest` and is green on the PR.
- [ ] `[macos-xcode]` Two simulators (iPad and iPhone) running the app with the same pairing payload see each other
      in Diagnostics within 15 s and a `checkOut` on one appears in the other's `counts` within 5 s, with no box
      running. Recorded as a short screen capture or log excerpt in the PR.
- [ ] `[owner-present]` On two physical iPads paired to the box (WS3 live): the same test over Wi-Fi with the box on,
      then with the box powered off. Filed as `needs-verification` if not done before the PR.
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

## Owner decisions
**Answered 2026-10-07** (closing comments on #6–#11): D1 yes (all Apple devices, free Apple account, repo public, macOS CI on every PR; decision 002); D2 yes, and featured in the demo (decision 001, WS8); D3 yes; D4: the box is a macOS laptop, the Pi on Debian Trixie is best-effort (decision 002); D5 yes; D6 yes, with the event renamed Richmond Riverfest (`trip-2026-10-18-riverfest`). Money is integer cents (decision 003). The lines below are the questions as asked; anything still open is marked.


- D1 (#6): iOS and Swift for tablets and the phone. Answered: yes. Also: which devices the owner has (two
  iPads and an iPhone is the recommended set; an Android device means CBL 4.1+ and a Kotlin build later).
- D5 (#10): peer discovery via the Multipeer Replicator over the venue Wi-Fi (travel router) with Bluetooth LE as
  the fallback transport (recommend: yes; blocks dispatch: no, the default applies).
- D3 (#8): unit-level QR payload `<SKU>#<serial>` (default applies).

## Verification plan

- Device-to-device sync between physical devices with the box off: owner-present (the owner holds the devices).
- Replication to the real Edge Server through the pairing QR, including the pinned certificate path if WS3 turns
  TLS on: agent with `box` plus a device, or owner-present.
- Bluetooth LE transport when Wi-Fi is absent: owner-present, Phase 0 nice-to-have; file it and move on if it does
  not work on first try.
- Simulator-to-simulator mesh on one Mac: `[macos-xcode]` criterion, agent with a Mac and Xcode.
- The `inBatch` guarantee against a real Couchbase Lite database (the unit test uses a real local database, not a
  fake; it counts as verified when `testEverySaleIsOneBatch` passes).

## Tasks

Milestones and acceptance tests (ws-design):
1. `[macos-xcode]` Project, package, models, HLC, the Swift ledger passing every fixture. Accept: `LedgerFixtureTests`
   green and matching WS1's report.
2. `[macos-xcode]` `CustodyStore` over Couchbase Lite with the `local` scope and the three writes; exception
   detection. Accept: the `SIABCoreTests` criteria.
3. `[macos-xcode]` `SyncCoordinator`: box replicator from a pairing payload, Multipeer mesh, Diagnostics screen, CI
   workflow. Accept: two-simulator criterion, CI green.
4. `[owner-present]` Two iPads and the box. Accept: the owner-present criterion, or its `needs-verification` issue.
5. `[any]` **PR.** One PR, `Closes #<issue>`; `needs-verification` issues filed and linked from "Not verified".
   Expected size: about 1,200 lines of code (tests and fixtures not counted; split the issue if it is over about
   1,500: the natural cut is `SyncCoordinator` plus Diagnostics into its own issue).

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
