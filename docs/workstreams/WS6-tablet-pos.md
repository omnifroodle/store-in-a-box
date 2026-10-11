# WS6: Tablet POS screens: scan, sell, take, return

**Milestone:** M1  **Depends on:** WS4  **Label:** `ws:6-tablet-pos`  **Agent type:** ws-design
**Issue:** #17

The blueprint. The architect (`ws-architect`) writes it before any code is dispatched; the PR is judged against it.

## Scope

What the audience sees on the right half of the screen. Four screens over WS4's `SIABCore`, built for a stage: big
type, one gesture per screen, the current mode named in words at the top so the room knows what the scan will do.
- **Sell**: scan units into a basket, pick a simulated tender, done. One `sale` transaction per unit, all in one
  batch, sharing a `basket` id.
- **Shelf**: live counts per SKU for this device and for the box, from WS4's `LedgerState`. This is the "counts
  update tablet to tablet" beat; it never refreshes, it just moves.
- **Custody**: two modes, **Take** (check out onto this device from the box) and **Return** (check in to the parent),
  plus **Pack** (check out from the store onto the box, the tablet acting for the box). The header reads
  "TAKING FROM box-07", "RETURNING TO box-07" or "PACKING store-richmond → box-07". A running list of units scanned
  this session with the allocation they fill or empty.
- **Exceptions**: open disputes with both transactions side by side (device, time, kind). `foreign_movement` and
  `unexpected_check_in` show the movement and its predecessor ("did not hold it"). Read-only; HQ resolves.
- A **status bar** on every screen: box link (connected / offline since), peer count, and this device's id. The
  gear opens WS4's Diagnostics.
- The **scanner**: the device camera, QR only, payload `<SKU>#<serial>`, a debounce so one label is one scan,
  haptic and a tone on accept, a visible reason on reject (unknown SKU, malformed payload, same unit twice in this
  basket).

Left for later: the upsell advisor and the query on screen (Phase 1), loyalty QR and tender on account (Phase 1),
demand capture (Phase 1), the compliance viewer (Phase 1), returns, receipts, any real payment.

## Files

Owned by this workstream:
- `app/StoreInABox/UI/` (new: `Sell/`, `Shelf/`, `Custody/`, `Exceptions/`, `Scanner/`, `Shared/` with the status
  bar and the stage typography)
- `app/StoreInABoxTests/` (new: view-model tests; counted as tests by name convention `*Tests`)

Named edits in neighbours' code:
- `app/StoreInABox/App/AppModel.swift`: register the four screens and the scanner in the composition root.
- `app/StoreInABox/App/RootView.swift` (the root view WS4 created): the tab bar with Sell, Shelf, Custody, Exceptions
  and the gear.
- `app/StoreInABox/Resources/Info.plist`: `NSCameraUsageDescription` if WS4 did not add it.
- `app/project.yml`: the new sources and the test target (XcodeGen generates `app/StoreInABox.xcodeproj/` from it;
  the generated `app/StoreInABox.xcodeproj/project.pbxproj` and
  `app/StoreInABox.xcodeproj/xcshareddata/xcschemes/StoreInABox.xcscheme` follow).
- `.github/workflows/ios.yml`: run `StoreInABoxTests` in both editions (exit criterion 2). Accepted at the gate on
  #118 (#115).

## Interfaces

**Consumes** WS4's `CustodyStore`, `SyncCoordinator`, `LedgerState`, `Product` and `Trip`; nothing in `SIABCore`
changes here (a needed change is a `for-foreman` issue naming the WS4 API).

**View models** (names fixed, `@MainActor`, each testable with a fake `CustodyStoring` protocol WS6 defines over
WS4's concrete class):
```swift
protocol CustodyStoring { checkOut(...); checkIn(...); sell(...); state: AnyPublisher<LedgerState, Never> }  // mirrors CustodyStore
final class SellViewModel     { basket: [BasketLine]; add(scan: ScanResult); remove(unit:); tender(kind: TenderKind) throws }
final class ShelfViewModel    { rows: [ShelfRow] /* sku, name, price, here: Int, box: Int */ ; filter: String }
final class CustodyViewModel  { mode: .take | .return_ | .pack; session: [CustodyLine]; apply(scan: ScanResult) throws }
final class ExceptionsViewModel { disputes: [DisputeRow] }   // grouped by dispute_key and fork-or-movement
                                                              // (kind in oversell/double_scan or not: a fork at a flagged
                                                              // movement shares its key, decision 009), open only
struct ScanResult { unit: UnitID; sku: String; serial: String }   // parsed from "<SKU>#<serial>", else nil with a reason
enum TenderKind: String { case cash, card_simulated }
```

**Sell semantics**: a basket holds distinct units; `tender(kind:)` calls `sell` once per unit inside a single
`inBatch` (WS4 exposes a batch helper or `sell` accepts an array; if neither exists, file the `for-foreman`
issue before building around it), with `basket` set to one UUID on every transaction, `price` from the product,
`tender.amount` the sum (money is integer cents, `{cents, currency}`, decision 003; the screen divides by 100). On success the basket clears and a confirmation shows the count and total for two seconds.

**Custody semantics**: `.take` → `checkOut(unit, from: box, to: thisDevice)`; `.return_` → `checkIn(unit)`;
`.pack` → `checkOut(unit, from: store, to: box, actingFor: box)`. A unit the record says is elsewhere, or has no
record, is still accepted (WS1 rule 6 raises an `unexpected_check_in`, rule 8 a `foreign_movement` for a sale or take
from a custodian this device does not act for; the movement stands); the line shows an amber "record disagrees" tag,
never a refusal.

**Shelf semantics**: one row per product that has any unit in this trip's ledger or is in the seeded catalog;
`here` is `counts[(thisDevice, sku)]`, `box` is `counts[(box, sku)]`. Rows animate on change.

**Stage typography** (so the reviewer can check it): body ≥ 20 pt, counts ≥ 44 pt, the mode header ≥ 28 pt bold,
status bar ≥ 17 pt, high-contrast default colour scheme, no information carried by colour alone.

## Contract changes

- CC3 (#4): `transaction.basket` (nullable string) and `tender.kind` enum `cash | card_simulated`. Already in the
  issue; no new change.

## Exit criteria

- [ ] `xcodebuild test -project app/StoreInABox.xcodeproj -scheme StoreInABox -destination 'platform=iOS Simulator,name=iPad (10th generation)'`
      passes; `StoreInABoxTests` includes `SellViewModelTests.testBasketRejectsDuplicateUnit`,
      `SellViewModelTests.testTenderSellsEveryLineWithOneBasketId`, `CustodyViewModelTests.testPackActsForBox`,
      `CustodyViewModelTests.testReturnOfDisagreeingUnitIsAcceptedAndTagged`,
      `ShelfViewModelTests.testRowsFollowLedgerState`, `ScannerParserTests.testPayloadGrammar` (accepts
      `JKT-RAIN-M-BLU#007`, rejects `JKT-RAIN-M-BLU`, `#007`, lowercase).
- [ ] `.github/workflows/ios.yml` (WS4's) runs this scheme too and is green on the PR.
- [ ] `[macos-xcode]` On two simulators with WS4's shared pairing payload: Sell on one, the Shelf on the other moves
      within 5 s; Take 3 units on one, the other's box count drops by 3. Screen capture or log excerpt in the PR.
- [ ] `[owner-present]` The Phase 0 acceptance beats on the real devices with the box and printed labels: sell by
      scan with the uplink cut; tablets consistent with the box powered off; tablet B takes 8, leaves range, sells
      3, returns, scans 5 back in, box and tablet agree; a deliberate double-scan shows one dispute in Exceptions on
      both tablets. Filed as `needs-verification` issues if not done before the PR (expected).
- [ ] `python3 scripts/board_check.py` reports no file outside this Files list for the PR.

## Owner decisions
**Answered 2026-10-07** (closing comments on #6–#11): D1 yes (all Apple devices, free Apple account, repo public, macOS CI on every PR; decision 002); D2 yes, and featured in the demo (decision 001, WS8); D3 yes; D4: the box is a macOS laptop, the Pi on Debian Trixie is best-effort (decision 002); D5 yes; D6 yes, with the event renamed Richmond Riverfest (`trip-2026-10-18-riverfest`). Money is integer cents (decision 003). The lines below are the questions as asked; anything still open is marked.


- D3 (#8): unit-level QR, payload grammar, label count (default applies).
- D6 (#11): tender kinds shown (`Cash`, `Card (simulated)`), currency and prices from the seed; whether the
  confirmation shows a total (recommend: yes). Blocks dispatch: no.

## Verification plan

- Everything the audience sees: the owner on the devices, with the labels, in a rehearsal (WS7). Owner-present.
- Camera scanning speed and false double-reads with printed labels under stage light: owner-present; the debounce
  value may need tuning and is a config constant, not a code change.
- Simulator checks: `[macos-xcode]` criterion, agent with a Mac and Xcode (scanning cannot be simulated; the
  simulator build exposes a text field behind the scanner for typing a payload, kept in DEBUG builds only).
- Type sizes from the back of a room: owner, eyes.

## Tasks

Milestones and acceptance tests (ws-design):
1. `[macos-xcode]` Scanner and parser, status bar, stage typography, Sell. Accept: `SellViewModelTests`,
   `ScannerParserTests`.
2. `[macos-xcode]` Shelf and Custody. Accept: `ShelfViewModelTests`, `CustodyViewModelTests`, two-simulator criterion.
3. `[macos-xcode]` Exceptions screen, tab bar, CI scheme. Accept: CI green.
4. `[owner-present]` Device run of the acceptance beats, or their `needs-verification` issues.
5. `[any]` **PR.** One PR, `Closes #<issue>`; `needs-verification` issues filed and linked from "Not verified".
   Expected size: about 1,100 lines of code (tests and fixtures not counted; split the issue if it is over about
   1,500: the cut is Exceptions plus the tab bar).

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
