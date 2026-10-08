# The tablet app (WS4 data layer)

One SwiftUI app for the iPads and the iPhone (iOS 17+), and `SIABCore`, the Swift package under it.

```
app/
  project.yml                 XcodeGen spec; StoreInABox.xcodeproj is generated from it
  StoreInABox.xcodeproj/      generated: run `xcodegen` here after editing project.yml, never edit by hand
  StoreInABox/App/            composition root (AppModel), placeholder root view; WS6 adds its screens here
  StoreInABox/Resources/      Info.plist (generated from project.yml's `info`)
  SIABCore/                   Swift package: models, HLC, the ledger port, CustodyStore, replication config
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

## Dependencies

Couchbase Lite Swift **Enterprise Edition** 4.1.2 through Swift Package Manager
(`couchbase-lite-swift-ee`): the `MultipeerReplicator` used for device-to-device sync ships only in EE.

## What lives where on the device

- `store` scope: `product`, `trip`, `allocation`, `transaction`, `exception`, the same names as the cluster, and the
  only collections any replicator carries (`Replication`).
- `local` scope: `unit_state` (the reducer's view of each unit, rebuilt by `CustodyStore.rebuild()`) and `device`
  (this device's identity). Never replicated.
- `CustodyStore` is the only writer to `store.*`: `checkOut`, `checkIn` and `sell` are each one `inBatch` (the
  transaction and the allocation it opens or closes), and `detectAndWriteExceptions()` writes only documents whose
  id does not exist yet.
