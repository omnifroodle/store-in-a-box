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
fixture, the same report as `uv run python -m siab_ledger check`. `Fixtures/ledger` is a symlink to that directory,
copied into the test bundle at build time, so a new fixture is picked up with no change here.

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
peers with last seen, and the live counts. "Pair with a box" scans the box's pairing QR, or takes its text pasted
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
- `local` scope: `unit_state` (the reducer's view of each unit, rebuilt by `CustodyStore.rebuild()`) and `device`
  (this device's identity). Never replicated.
- `CustodyStore` is the only writer to `store.*`: `checkOut`, `checkIn` and `sell` are each one `inBatch` (the
  transaction and the allocation it opens or closes), and `detectAndWriteExceptions()` writes only documents whose
  id does not exist yet.
