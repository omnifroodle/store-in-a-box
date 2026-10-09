# Store in a Box

A Couchbase demo. A retail store packs part of itself into a box (Couchbase Edge Server plus a few tablets
running Couchbase Lite), sells at a venue with no connectivity, **splits into smaller pieces that each keep
selling, merges them back in any order**, and rejoins the chain through Capella App Services with every unit
and every dollar accounted for. Agents in Capella plan the trip and prove their claims; a small model on the
box helps the clerk.

The product is the demo. The platform is the product.

**The beats**

1. Place: agents score venues and check permits, with the passage behind every claim.
2. Pack: scan units out of the store onto the box. Custody, not counts.
3. Sell: pull the cable. Two tablets, device-to-device sync, hybrid-search upsell, offline loyalty.
4. Split: a tablet walks off with eight jackets and is still a store. Then a phone splits off the tablet.
5. Merge: in any order, tablet to tablet, no cloud. Plug in: kilobytes, and the conservation query holds.
6. Rejoin: forks become exceptions with both sides attached, an explainer, a retrospective that feeds the next trip.

**The pattern underneath: a conflict-free ledger**

Custody never conflicts, by construction. Every movement of a unit (pack, take, return, sale) is an immutable
document written once by one device and naming the movement before it; counts are derived, never edited. Two sales
of the last unit are a fork in that unit's history, found by the same rules on every tablet and at HQ, and the fork
becomes an exception with both sales attached. No resolver, no node choosing between two versions of a document:
[`docs/architecture/conflict-free-ledger.md`](docs/architecture/conflict-free-ledger.md).

| | |
|---|---|
| Spec | [`docs/SPEC.md`](docs/SPEC.md), phased with acceptance criteria |
| Architecture | [`docs/architecture/overview.md`](docs/architecture/overview.md) and one note per component; the custody pattern is [`docs/architecture/conflict-free-ledger.md`](docs/architecture/conflict-free-ledger.md) |
| Product page | `site/`, published to GitHub Pages by `.github/workflows/pages.yml` |
| Deck | `deck/`, not started |
| Status | Spec and architecture notes complete. Phase 0 not started. |
| Roadmap | [`docs/ROADMAP.md`](docs/ROADMAP.md): enhancements to build when budget allows, including the Couchbase AI Data Plane possibilities, which are not part of the demo |

## Layout

`docs/` spec and architecture notes · `site/` product page · `deck/` customer deck (to come) ·
`scripts/build-site.mjs` assembles `site/`, `deck/` and `docs/images/` into `_site/`.

## Building the demo

Build in the phases the spec lays out, in order, and demo after each one. Phase 0 is sync and custody with no
AI at all: a pack plan entered by scanning, two tablets selling with the uplink cut, a one-level split and
merge, a staged oversell that becomes an exception, and the conservation query holding throughout. The cut line
for a first showing is the end of Phase 1.

Open questions that should be settled before Phase 0 are listed at the end of the spec.
