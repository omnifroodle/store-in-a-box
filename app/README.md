# The tablet app (WS4 data layer)

One SwiftUI app for the iPads and the iPhone (iOS 17+), and `SIABCore`, the Swift package under it.

```
app/
  project.yml                 XcodeGen spec; StoreInABox.xcodeproj is generated from it
  StoreInABox.xcodeproj/      generated: run `xcodegen` here after editing project.yml, never edit by hand
  StoreInABox/App/            composition root (AppModel), root view; WS6 adds its screens here
  StoreInABox/Diagnostics/    the Diagnostics screen, pairing (camera QR, or pasted text) and the QR scanner view
  StoreInABox/Resources/      Info.plist (generated from project.yml's `info`)
  SIABCore/                   Swift package: models, HLC, the ledger port, CustodyStore, pairing, SyncCoordinator
    Tests/SIABCoreTests/      unit tests; Fixtures/ holds symlinks into contracts/ and ports/, never copies
```

## Build and test

```sh
xcodebuild test -project app/StoreInABox.xcodeproj -scheme SIABCore \
  -destination 'platform=iOS Simulator,name=iPhone 16'     # any available iPhone simulator works
swift test --package-path app/SIABCore                     # the same tests on macOS, faster to iterate
```

`LedgerFixtureTests` runs every fixture in `contracts/fixtures/ledger/` and prints one `PASS <name>` line per
fixture, the same report as `uv run python -m siab_ledger check` (CI diffs the two). `Fixtures/ledger` is a symlink to
that directory, copied into the test bundle at build time, so a new fixture is picked up with no change here. It reads
the documents as raw JSON and runs rule 0 first (`DocumentCheck.ingest`, decision 010), so a fixture can carry
documents that fail their schema and its `expected.drops` is compared.

`DocumentCheck` (`SIABCore/Sources/SIABCore/Validation.swift`) is the Swift validator: the six collection schemas
written in Swift (`StoreSchema`), an evaluator that reports errors as `jsonschema` does, the cross-field rules and the
id template. `DocumentCheckTests` checks it against the `contracts/fixtures/docs/` corpus, with the code the Python
reference gives each file, and checks that each Swift schema is the contract file, keyword for keyword: a schema
change fails there until `StoreSchema` mirrors it.

The differential test runs both ports on generated sets, invalid documents included, and compares the reports
(`scripts/ledger_diff.sh [SEED]` on a Mac; CI's `community` leg runs it with seed = the run number).
`LedgerDifferentialTests` is the Swift half: it reads `SIAB_DIFF_SETS` and writes `SIAB_DIFF_OUT`, and is skipped
without them (on a simulator, pass them as `TEST_RUNNER_SIAB_DIFF_SETS` and `TEST_RUNNER_SIAB_DIFF_OUT`).

## Couchbase Lite edition

Couchbase Lite Swift 4.1.2 through Swift Package Manager. **Community Edition** (`couchbase-lite-swift`) is the
default: a fresh clone builds, tests and runs with it, and syncs with the box. **Enterprise Edition**
(`couchbase-lite-swift-ee`) is used only when you opt in, and it is what device-to-device sync needs: the
`MultipeerReplicator` ships only in EE, so `SIABCore` compiles the mesh only under the `COUCHBASE_ENTERPRISE`
condition that `SIABCore/Package.swift` sets for it. With Community Edition, Diagnostics shows
`mesh: unavailable (Community Edition)`.

> Couchbase Lite Enterprise Edition is used only when you opt in. Checking that your use of it is covered by its
> licence is your responsibility.

The one switch is the environment variable `SIAB_CBL_EDITION` (`community`, the default, or `enterprise`), read by
`SIABCore/Package.swift` when Swift Package Manager or Xcode resolves the package:

```sh
SIAB_CBL_EDITION=enterprise xcodebuild test -project app/StoreInABox.xcodeproj -scheme SIABCore \
  -destination 'platform=iOS Simulator,name=iPhone 16'
SIAB_CBL_EDITION=enterprise swift test --package-path app/SIABCore
open --env SIAB_CBL_EDITION=enterprise app/StoreInABox.xcodeproj    # Xcode: quit it first so it sees the variable
```

Switching edition in a checkout that has already built: clear the resolved packages first (`rm -rf
app/SIABCore/.build`; in Xcode, File > Packages > Reset Package Caches, or a fresh DerivedData), or the previous
edition's binary is reused. The committed `SIABCore/Package.resolved` pins Community Edition; an Enterprise build
rewrites it locally, so do not commit that change. CI (`.github/workflows/ios.yml`) builds and tests both editions.

## Pairing and Diagnostics

The Diagnostics screen (the root until WS6's screens land) shows this device, the trip and box, the box link with its
document counters and unpushed tail (`unpushed: N movements (oldest 14:02)`, `last pushed 14:05`), the mesh and its
peers with last seen, the live counts, and **Dropped documents**: `dropped: N documents`, then the newest ten, each
`<collection> <id>` over `<code in words> · <source> · <HH:mm>` (the words are HQ's: `missing field`, `unknown
field`, `newer schema: update the app`, ...; the source is `local`, `box` or `peer`). Every transaction and exception
that fails its schema is dropped there, not reduced and never skipped silently; when N > 0 the status bar shows an
amber `N dropped` that opens Diagnostics. A Debug build adds "Drop check: write a v 2 take" to the movement check,
for the two-device check that a peer lists it. "Pair with a box" scans the box's pairing QR, or takes its text pasted
(the simulator has no camera); a payload with a malformed device, box, trip, address or fingerprint is refused. The
identity and the non-secret pairing fields go to `local.device`, the Edge Server password to the keychain. "Rebuild
derived state" re-reduces every movement. "Movement check" packs a unit onto the box or takes it from the box, for
the mesh and box checks.

Simulators: the keychain needs a signed app, so build for the simulator without `CODE_SIGNING_ALLOWED=NO` (Xcode
signs it to run locally; no team needed). A Debug build pairs at launch from `SIAB_PAIRING`, for scripted checks:

```sh
SIMCTL_CHILD_SIAB_PAIRING='<payload JSON>' xcrun simctl launch <device> com.example.storeinabox
xcrun simctl spawn <device> log stream --predicate 'subsystem == "com.example.storeinabox"'   # peers and counts
```

The two-simulator mesh check (blueprint exit criterion): an Enterprise build on an iPad and an iPhone simulator,
paired with payloads for the same box, trip and peer group (`tablet-a`, `phone-1`), no box running. Each sees the
other in Diagnostics, and a movement on one appears in the other's counts. Simulators have no Bluetooth LE; the mesh
runs over Wi-Fi (DNS-SD) and Diagnostics notes the missing transport.

## What lives where on the device

- `store` scope: `product`, `trip`, `allocation`, `transaction`, `exception`, the same names as the cluster, and the
  only collections any replicator carries (`Replication`).
- `local` scope: `unit_state` (the reducer's view of each unit, rebuilt by `CustodyStore.rebuild()`), `device`
  (this device's identity) and `drop_log` (rule 0's drops, one entry per `(collection, id)`, at most 200, the oldest
  `last_seen` evicted first; each new entry logged once at warning, category `ledger`). Never replicated.
- `CustodyStore` is the only writer to `store.*`: `checkOut`, `checkIn` and `sell` are each one `inBatch` (the
  transaction and the allocation it opens or closes), and `detectAndWriteExceptions()` writes only documents whose
  id does not exist yet.
