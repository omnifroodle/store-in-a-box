# Store in a Box

Product spec for a Couchbase demo. The product is the demo: a retail store that
packs itself into a box, sells offline at a remote venue, and rejoins the chain
with a clean reconciliation. Four AI agents plan the trip and explain what
happened. Couchbase Capella, Couchbase Edge Server and Couchbase Lite carry the
data; Capella AI Services and Agent Catalog carry the agents.

Status: draft v0.1, 2026-10-07. Author: Matt Overstreet.

---

## 1. What this is

A retailer wants to sell at a farmers market, a festival, a trade show, a sneaker
drop. Today that means a week of permit phone calls, a guess at what to bring,
a POS that falls over when the venue wifi does, and a reconciliation argument
on Monday. Store in a Box shows one data platform doing the whole trip:

1. **Place.** Agents pick where to go and confirm you are allowed to sell there.
2. **Pack.** A subset of catalog, inventory and customers moves to the box.
   Inventory moves by custody, not by copy.
3. **Sell.** Tablets sell with no connectivity. AI helps the clerk, offline.
4. **Reconcile.** The box comes home. Every unit is accounted for. Conflicts
   become exceptions with explanations, not lost sales.
5. **Rejoin.** Customers, returns and demand signals flow back into the chain
   and feed the next trip.

And one property that runs through all five: **the store can split.** A box
can hand part of itself to a tablet that walks off to the other end of the
festival and becomes its own store. That tablet can split again. Every piece
keeps selling, every piece reconciles with whichever piece it meets next, and
the whole chain keeps running the entire time. The store is not a thing in one
place; it is a tree of custody that can divide and merge without stopping.

The audience is retail and field-operations buyers, plus the SEs who will
reuse the pattern. The message is: **the cloud picks the destination, the edge
runs the day, and the database is the message bus between every agent.**

### 1.1 What this is not

- Not a production POS. No real payments. Tender is simulated.
- Not legal advice. The compliance agent produces a cited checklist with
  confidence states; it never files anything.
- Not a fleet optimizer in v1. One box, two or three tablets.

---

## 2. Demo narrative

Twelve minutes, one presenter, one assistant on a tablet. Split screen: Capella
dashboard on the left, tablet on the right, a visible network toggle between.

| Beat | What happens | What it proves |
|---|---|---|
| 1 | Venue scorer proposes five sites for next weekend with reasons | Columnar + geo + agent |
| 2 | Compliance agent kills two, flags one for confirmation, cites every claim | RAG with provenance and evaluation |
| 3 | Research agent suggests three inventory changes with evidence; presenter accepts two | Agent output as reviewable documents |
| 4 | Packing agent produces the pack list; presenter approves; custody transfers and the box fills | Channels, filtered replication, custody model |
| 5 | **Pull the network cable.** Sell five items across two tablets. Live counts update tablet to tablet | CBL peer-to-peer, live queries |
| 6 | Clerk asks the tablet "anything waterproof in a medium" and gets an answer. Scans a shell; the tablet proposes socks and a pack cover with a reason. The query goes on screen | On-device hybrid search, small model |
| 7 | Clerk logs "asked for, didn't have" with a voice note | Demand capture |
| 7a | A loyalty member scans their QR, types four digits, buys on account. Allowance drops on screen | Offline identity and credit, pessimistic by policy |
| 8 | Fire marshal walks up; the approved permit HQ attached before the cable came out is on the tablet. Assistant records the inspection with a photo, offline | Permit flow both directions, blobs sync |
| 9 | **Split the store.** Assistant takes tablet B, "takes" eight jackets and a float of cash, and walks out of range of the box. Both halves keep selling. Tablet B's clerk splits again onto a phone for a roaming seller | Recursive custody, every piece is a store |
| 10 | Tablet B comes back into range. The two halves reconcile with each other, not with the cloud. Counts agree. Then the phone comes back and reconciles with tablet B | Merge in any order, no coordinator |
| 11 | Meanwhile HQ sells the last unit of a SKU the box also has one of. Box sells it too | Conflict staged |
| 12 | **Plug the cable in.** Byte counter shows a few KB. Capella catches up. Conservation query still sums correctly across store, box, tablet B and phone. The inspection record lands in the HQ permit queue with its photo | Delta sync, custody conservation across the whole tree, field to office |
| 13 | Exception appears: oversell. Resolver wrote a third document with both sales. Agent drafts the customer message | Custom conflict resolution as app code |
| 14 | Trip retrospective agent writes the report and three recommendations; venue scorer's inputs now include this trip | Loop closes |

Beat 5 is the moment. Everything before it earns the right to pull the cable;
everything after it shows the cable did not matter. Beats 9 and 10 are the
second moment: the store divides, every piece runs itself, and the pieces find
each other again without anyone in charge.

---

## 3. Architecture

Three tiers. The demo is about what happens when any link between them is cut.

```
+-------------------+        +---------------------+        +------------------+
|  Tablets (2-3)    | <----> |  The Box            | <----> |  Capella         |
|  Couchbase Lite   |  P2P   |  Couchbase Edge     |  sync  |  App Services    |
|  POS app          |  and   |  Server             |  when  |  Data, Search,   |
|  on-device vector |  to    |  local hub, small    |  able  |  Columnar,       |
|  search           |  box   |  model runtime       |        |  Eventing,       |
|  small model opt. |        |  (Raspberry Pi or    |        |  AI Services,    |
|                   |        |   laptop)            |        |  Agent Catalog   |
+-------------------+        +---------------------+        +------------------+
```

**Tablets.** Couchbase Lite with vector search enabled. The POS, the clerk
copilot, the compliance viewer, the demand-capture form. Tablets replicate to
the box and to each other (peer-to-peer) so the box is not a single point of
failure.

**The box.** Couchbase Edge Server as the venue hub. Holds the full packed
dataset, serves the tablets, replicates to Capella when it has a link. Also
runs a small model (Ollama or similar) for the on-box agents: clerk copilot,
evening briefing, trip retrospective draft. The box is the thing you carry.

**Capella.** System of record. App Services for sync and channel-based access
control. Search for hybrid retrieval over ordinances and product catalog.
Columnar for the venue scorer's analytics. Eventing for reorder triggers and
exception routing. AI Services for cloud-side model calls and embeddings. Agent
Catalog for tool and prompt definitions so agent tool calls are visible and
versioned.

**Principle: agents talk through documents.** No agent calls another agent.
Each writes its findings as documents; the next reads them. This is what lets
an agent run on the box offline and still participate, and it makes the audit
trail free.

**Principle: every node is a store.** The chain, a store, a box, a tablet and a
phone are the same kind of thing at different sizes: a custodian holding
allocations and writing transactions. A tablet that leaves the box's range is
not a disconnected client, it is a smaller store. There is no coordinator a
split has to ask and no coordinator a merge has to report to. Two pieces that
meet reconcile with each other; the result is correct regardless of the order
the pieces meet in or whether the cloud ever sees the intermediate states. This
is what Couchbase Lite peer-to-peer replication plus the custody model buys,
and the demo should say it in one sentence.

**Principle: phone home lazily.** Nothing in the venue waits on Capella. Every
scan, sale, split and merge is a local write to the device's own Couchbase
Lite database and is correct the moment it lands there. Replication to a peer,
to the box, and eventually to Capella is continuous and opportunistic: it runs
whenever a link exists, resumes from a checkpoint when one reappears, and
never blocks the operation that produced the data. The cloud is informed, not
consulted. That single posture is what makes the cable pull, the split, the
terrible link and the box-dead mode all the same demo rather than four
different features.

### 3.0 The Couchbase components, named

The demo is a platform story, so every beat should name the component doing
the work. These are the names to use on screen and in the deck.

| Component | Role in Store in a Box | Where it shows in the demo |
|---|---|---|
| **Couchbase Lite** | The database on every tablet and phone. Collections, SQL++, live queries, vector search, blobs, database encryption. Every scan, sale, split and merge is a local write here first | Beats 5, 6, 7, 9 |
| **Device-to-device sync** (Couchbase Lite peer-to-peer replication) | Tablets and phones replicate directly to each other and to the box with no server in the path. This is what lets the store split, run as pieces, and reconcile piece to piece while offline | Beats 5, 9, 10, and the box-dead mode |
| **Couchbase Edge Server** | The box. A lightweight server in the venue that the tablets sync to, that holds the whole packed dataset, runs the on-box agents, and carries the venue's changes up to Capella when it can | Beats 4, 8, 12, and the terrible-link mode |
| **Capella App Services** | The sync tier between the box and the cloud. Channels decide which documents reach which custodian, the sync function validates and routes every write, and conflicts hand off to the application's resolver | Beats 4, 12, 13, revocation drill |
| **Capella** | System of record. Data Service for the documents, Search for hybrid retrieval over ordinances and catalog, Columnar for the venue scorer, Eventing for reorder and exception routing, AI Services for cloud model calls and embeddings, Agent Catalog for the agents' tools and prompts | Beats 1, 2, 3, 12, 13, 14 |

Two things to say about device-to-device sync specifically, because it is the
least familiar and the most differentiating:

- **Multiple units at one sale.** Three tablets at one booth are three
  replicas of the same store. A sale on one shows on the others in about a
  second, with the box up or down, because they replicate to each other
  directly. There is no "primary tablet."
- **Reconciliation without the cloud.** When tablet B comes back from the far
  end of the festival, it reconciles with the box, or with tablet A if the box
  is down, and the result is final. Capella learns about it later and has
  nothing to adjudicate. Device-to-device sync is what makes "reconcile" a
  thing that happens between any two custodians, not a thing that happens in
  the cloud.

### 3.1 Connectivity modes to demo

| Mode | How to produce it | What must still work |
|---|---|---|
| Normal | Box on venue wifi | Everything |
| Box offline | Pull the box's uplink | All selling, clerk copilot, compliance viewer, tablet-to-tablet sync |
| Box dead | Power off the box | Selling continues tablet-to-tablet; counts stay consistent between tablets |
| Terrible link | Throttle uplink to 2G speeds | Sync progresses in background, checkpoints survive interruption |
| Partial | Kill uplink mid-sync, restore | Sync resumes from checkpoint, not from zero |
| Split | Tablet walks out of range of the box with units scanned onto it | Both halves sell; they reconcile with each other on return without the cloud |
| Split again | Phone takes units from the out-of-range tablet | Three-level tree; merges in any order give the same result |

---

## 4. Data model

One bucket, `retail`. Scope `store` for operational data, scope `agents` for
agent inputs and outputs, scope `ref` for reference material. Collections below
are the v1 set.

### 4.1 Custody, not counts

Inventory is modeled as **units in custody**, not as counts that get merged.

```
allocation::<id>
{
  type: "allocation",
  sku: "JKT-RAIN-M-BLU",
  qty: 12,
  custodian: "box-07",
  from: "store-richmond",
  trip: "trip-2026-10-18-maker-fair",
  created: ..., status: "active" | "closed"
}
```

Pack creates an allocation and decrements the store's on-hand in the same
write. Sales on the road decrement the allocation. Transfers between boxes
create a new allocation and close the old one for the moved qty. Rejoin closes
the allocation and returns the remainder to store on-hand.

**Scan to check out, scan to check in.** Custody moves by scanning, and only by
scanning. Every unit, or every case of units, carries a barcode or QR. Any
device that holds a Couchbase Lite database is a custodian and has two buttons:

- **Check out.** Scan a unit while the device is the destination. Custody moves
  from whoever holds it (store, box, another tablet) to this device. This is
  how Pack happens: the packing agent's plan is a pick list, and the box fills
  by scanning. It is also how a split happens: tablet B scans eight jackets off
  the box and walks away with them.
- **Check in.** Scan a unit while the device is the source. Custody moves back
  to the parent, or to whichever custodian is in range and accepting. This is
  how Rejoin happens, and how a merge happens.
- **Sell** is check out to a customer, with a tender attached.

The pack list, the split, the merge and the sale are all the same gesture and
the same document shape. There is no separate transfer UI, no reconciliation
screen for the clerk, and no count to enter by hand. A unit is wherever it was
last scanned. Checking in a unit that the record says is elsewhere does not
fail; it writes an exception, because the physical scan is the stronger
evidence and the record is what needs explaining.

Scanning also carries the no-signal case for free: a scan is a local write to
the device's own database and replicates whenever it can. Two devices that
both scanned the same unit produce a conflict the resolver turns into an
exception, which is exactly what a double-scan should be.

**Recursive custody.** An allocation can have a parent. The store allocates to
the box, the box allocates to tablet B, tablet B allocates to a phone. Each
custodian is a store at its own scale, with its own allocations, transactions
and exceptions. Splits and merges are moves in this tree:

```
allocation::<id>
{
  ...,
  parent: "allocation::<id of the allocation this was split from>" | null,
  custodian: "tablet-B",
  split_at: ..., merged_at: null
}
```

A merge closes the child and returns its remaining qty to the parent. Merges
can happen in any order and at any level: the phone can merge back into tablet
B after tablet B has already merged into the box, and the result is the same
as if it had happened the other way round. No node needs the cloud to split or
merge; two devices in range of each other are enough. The chain, the store and
every other node keep selling throughout.

**Invariant:** for every SKU, at every point in time, across every level of
the tree,

```
store_on_hand + sum(active allocation qty at every level) + sold
  + returned_to_stock = opening_on_hand + received
```

The demo runs this as a live query in Capella and shows it holding before,
during and after the trip, including while the tree is three deep and two of
its nodes are out of range. Any gap is shrinkage by definition and becomes an
exception document.

### 4.1a Loyalty customers buying offline

Loyalty members can buy on their account with no connectivity: store credit,
points, or "charge it to my account and settle later." The posture is
**pessimistic by default, and still a real purchase.** The retailer decides
how much risk to carry to the venue, and the box enforces that number without
asking anyone.

**Allowance is custody.** Before the trip, Capella computes a per-customer
offline allowance for members in the venue's region (store credit on hand,
points balance, and an account-charge limit set by policy, say the lesser of
their trailing average basket times two and a flat cap). The allowance is an
allocation, exactly like inventory:

```
allowance::<id>
{
  type: "allowance",
  customer: "cust-8841",
  kind: "credit" | "points" | "account",
  amount: 120.00,
  custodian: "box-07",
  parent: null,
  trip: "trip-2026-10-18-maker-fair",
  expires: "2026-10-20T00:00Z",
  status: "active"
}
```

Capella reserves the amount against the customer's balance when the allowance
is created, so the same credit cannot be spent online and at the venue. The
box can split an allowance to a tablet the same way it splits inventory, so a
customer served by tablet B at the far end of the festival spends against
tablet B's slice. A customer spending at two custodians that together exceed
the allowance produces a conflict the resolver turns into an exception, never
a silent overdraft. Rejoin closes the allowance and releases the unspent
reservation. Same tree, same invariant, same gestures.

**Identity, offline.** The customer presents a QR from their loyalty app or
card. The QR carries a token signed by the retailer's key and bound to the
customer id, with a validity window. The tablet verifies the signature with
the public key it already holds; no network, no lookup. A second factor is
cheap and worth showing: last four of a phone number typed by the customer,
checked against a salted hash in the synced record. Lost card plus a shoulder
glance is not enough.

**What goes to the box, and how.** Only members in the venue's region, only
the fields the venue needs: customer id, display name, tier, the allowance,
the phone hash, the public key. No full address, no payment instruments, no
history. Replicated through the `customers:<region>` channel, encrypted at
rest on every device with Couchbase Lite's database encryption, key held by
the box and vended to tablets at pairing. Revocation of a tablet purges the
customer documents like everything else, and the box can stop vending the key
to a tablet that does not return.

**Pessimistic knobs the retailer turns.** All of these are policy documents
synced down, not code:

- Allowance formula and flat cap per tier.
- Whether `account` kind is allowed at all for this venue, or only `credit`
  and `points`.
- Allowance expiry, defaulting to the trip end.
- Whether a new member can enroll offline (yes, with a provisional allowance
  of zero until the box phones home and Capella grants one).
- Maximum offline exposure per box: the sum of all active allowances the box
  may hold. The packing agent respects it when choosing which members to
  include.

**Reconcile.** When the box phones home, each account charge posts against the
customer's real balance. Because the reservation already held the amount,
posting cannot fail for insufficient funds; it can only surface an exception
if a split allowance was double-spent across custodians, and that exception
carries both transactions. Points earned offline post in the same pass.
Loyalty-attributed sales from the trip feed the venue scorer: members who
bought at the pop-up are the strongest evidence for returning.

**Demo beats.** A member scans their QR with the cable out, types four digits,
buys on account. The tablet shows the remaining allowance drop. Same member
walks to tablet B and tries to spend past the remainder; tablet B declines
locally with the reason. Plug the cable in, the charge posts, the reservation
releases, and the customer document in Capella shows the trip's purchase.

**Honest limits.** This is not card authorization. No PAN, no issuer, no PCI
scope; the only thing at risk is the retailer's own credit to its own known
customers, bounded by a number they chose. Say that once in the demo; it is
why the pessimistic posture is credible rather than hand-wavy.

### 4.2 Collections

**scope `store`**

| Collection | Purpose | Synced to box? |
|---|---|---|
| `product` | Catalog: name, price, images, category, embedding | Yes, filtered: no cost, supplier or margin fields |
| `inventory` | Store on-hand per SKU per location | No. Box sees allocations only |
| `allocation` | Custody records (above) | Yes, for this trip's custodian |
| `transaction` | Sales, returns, tenders. Stamped with jurisdiction and tax basis | Yes, box writes, Capella reads |
| `customer` | Loyalty records | Yes, filtered to the venue's region, PII minimized, encrypted at rest |
| `allowance` | Per-customer offline spending allocation (section 4.1a). Reserved in Capella, split and merged like inventory | Yes, for this trip's custodians |
| `policy` | Venue and trip policy: allowance formula, caps, tender kinds allowed, return policy variant, permit gates | Yes |
| `permit` | One per requirement per trip. State machine worked by the agent, the back office and the field (section 7.3a). Attachments are blobs | Yes, both directions |
| `exception` | Conflicts, oversells, shrinkage, anything a human must look at | Yes, both directions |
| `demand_signal` | "Asked for, didn't have", research agent suggestions, kiosk orders | Yes, both directions |
| `trip` | One per trip: venue, dates, box id, status, links to agent outputs | Yes |

**scope `agents`**

| Collection | Purpose |
|---|---|
| `venue_candidate` | Venue scorer output: site, score, reasons, evidence refs |
| `compliance_check` | Compliance agent output: per-claim checklist with provenance and status |
| `inventory_suggestion` | Research agent output: suggested SKU changes with evidence |
| `pack_plan` | Packing agent output: proposed allocations, accepted or rejected per line |
| `briefing` | On-box evening and morning briefings |
| `retrospective` | Trip report written at rejoin |
| `eval_run` | Agent evaluation results against the gold set |

**scope `ref`**

| Collection | Purpose |
|---|---|
| `ordinance` | Chunked, embedded regulatory text with jurisdiction, source URL, retrieved date, last-amended date if known |
| `jurisdiction` | Geo boundaries and metadata for tax and permit lookups |
| `gold_site` | Twenty sites with known-correct compliance answers, for evaluation |

### 4.3 Channels

App Services channels scope what each box and tablet receives.

- `trip:<trip-id>` carries that trip's allocations, allowances, transactions,
  exceptions, demand signals, policy, compliance check and pack plan.
- `catalog:<region>` carries the filtered product subset.
- `customers:<region>` carries the filtered customer subset.
- `box:<box-id>` carries box-specific config and briefings.

A tablet's access is the union of its box's channels. Revoking a tablet's user
removes its access to every channel; on next contact its documents are purged.

### 4.4 Conflict policy

Default is last-write-wins for everything that is not inventory or money.
For `allocation` and `transaction`, a **custom conflict resolver** runs on the
box and in App Services:

- Two decrements of the same allocation that together exceed qty do not pick a
  winner. The resolver writes an `exception` of type `oversell` with both
  transactions attached and a proposed resolution (backorder, substitute,
  refund), and leaves the allocation at zero.
- The same rule applies to `allowance`: two charges against split slices that
  together exceed the amount produce an `exception` of type `overspend` with
  both transactions, and the allowance goes to zero. The customer is never
  silently overdrawn and the retailer never silently eats it; a human decides.
- Conflicting edits to a transaction keep the version with the later tender
  timestamp and attach the loser as `superseded`.

The resolver is application code, and the demo says so.

### 4.5 Time

Transactions carry the box's clock and the tablet's clock. Ordering uses the
box's clock when the box was reachable at write time, otherwise a hybrid
logical clock on the tablet. The demo sets one tablet's clock wrong on purpose
and shows the ledger still orders correctly.

### 4.6 Provenance

Every agent output document carries, per claim:

```
{
  claim: "Transient vendor license required",
  status: "verified" | "needs_confirmation" | "not_found",
  checks: { grounded: true, fresh: true, jurisdiction_match: true },
  evidence: [{ source_url, quoted_passage, retrieved_at, doc_id, jurisdiction }],
  confirmed_by: null | { who, when, how, note }
}
```

Provenance lives in the same document as the answer. Click a claim on the
tablet, see the passage. Offline.

---

## 5. Phases

Each phase has a scope, demo beats and acceptance criteria. Build in order;
demo after each one.

### Phase 0: Skeleton (no AI)

**Scope.** Capella cluster, App Services, one Edge Server box, two tablets with
a minimal POS. Product, allocation, transaction collections. Channels. Custody
model with scan to check out and scan to check in. Peer-to-peer between
tablets. One-level split: a tablet takes custody from the box and merges back.

**Acceptance.**
- Pack happens by scanning units out of the store onto the box. Store on-hand
  drops per scan.
- Tablets sell by scan against allocations with the box's uplink cut.
- Tablets stay consistent with each other with the box powered off.
- Tablet B scans eight units off the box, leaves range, sells three, returns,
  scans five back in. Box and tablet agree without the cloud. The box kept
  selling throughout.
- Restoring the uplink reconciles with a visible byte count under 100 KB for a
  day of fifty transactions.
- The conservation query holds before, during and after, including while
  tablet B is out of range.
- One staged oversell produces one exception document with both transactions.
- One deliberate double-scan produces one exception, not a lost or duplicated
  unit.

### Phase 1: Sell well (edge AI)

**Scope.** On-device vector search over packed products. Clerk copilot on the
box with local-query tools. Demand capture with voice note blob. Compliance
viewer reading a hand-written compliance document synced down. Permit PDF as a
blob. Two-level split: a phone takes custody from tablet B while tablet B is
already away from the box. Loyalty offline purchase: signed QR, phone-hash
second factor, allowance enforced locally, encrypted customer collection.

**Acceptance.**
- Member buys on account with the uplink cut. Allowance decrements on the
  tablet. The same member is declined locally at tablet B for exceeding the
  remainder, with the reason shown.
- A forged or expired QR is rejected offline.
- On reconnect the charge posts and the reservation releases in Capella. A
  staged double-spend across split slices yields one `overspend` exception.
- Customer documents on a tablet are unreadable without the box-vended key.
- Phone scans three units off tablet B, sells one, merges back into tablet B.
  Tablet B then merges into the box. Repeat with the merges in the opposite
  order (tablet B into box first, phone into tablet B after). Final state is
  identical both ways.
- "Anything waterproof in a medium" returns ranked products offline, under two
  seconds on the tablet.
- Upsell advisor proposes one or two in-custody add-ons within a second of the
  second scan, offline; with the box up a reason line appears, with the box
  down the suggestions still do. Accept/decline is recorded on the
  transaction.
- Copilot answers "what's the return policy here" from the synced compliance
  document, and correctly says it does not know margin.
- Demand signal with audio blob syncs up on reconnect.
- Lost-tablet drill: revoke, reconnect, documents gone.

### Phase 2: Reconcile and rejoin (cloud AI)

**Scope.** Reconciliation explainer agent. Returns at the flagship for road
purchases. Eventing reorder trigger. Trip retrospective agent. Exceptions
routed to a review queue. Permit flow: `permit` state machine, HQ queue screen,
field confirmation, inspection and flag from the tablet, policy-driven gates.
The compliance agent itself arrives in Phase 3; here the `drafted` permits are
seeded by hand.

**Acceptance.**
- HQ approves a permit with an attached PDF; it is on the tablet after sync
  and viewable with the uplink cut.
- Field records an inspection with a photo offline; it appears in the HQ queue
  on reconnect, with the photo.
- Flipping a tender gate in policy from HQ changes what the tablet allows after
  the next sync, and the tablet shows which permit state caused it.
- No code path lets an agent write a permit state beyond `drafted`.
- Explainer writes the narrative for a trip with 50 packed, 44 sold, 3
  returned, 2 transferred, 1 unaccounted, and names the last scan of the
  missing unit.
- A road purchase returns at the flagship in one lookup.
- Retrospective is written within a minute of rejoin and links to every
  exception and demand signal.

### Phase 3: Place (planning agents)

**Scope.** Venue scorer on Columnar. Compliance checker with full evaluation
(section 7). Research agent over the retailer's own signals (reviews, searches,
wishlists, weather, event calendar); social feeds optional. Packing agent that
reads the other three. Agent Catalog for all tool definitions.

**Acceptance.**
- Scorer returns five ranked candidates with reasons and evidence refs from
  seeded data.
- Compliance checker scores at least 90% claim-level accuracy on the gold set
  and never reports `verified` on a poisoned chunk.
- Research agent produces at least three suggestions with evidence per venue;
  accept/reject is recorded.
- Packing agent's plan references all three upstream documents and the
  presenter can accept or reject per line on the tablet.

### Phase 4: Stretch

Second box with box-to-box custody transfer. Pricing proposals within an HQ
band, approved offline. Customer-facing kiosk with home-delivery orders.
Fleet dispatcher. Shrinkage patterns across trips.

---

## 6. Agents

All agents read and write documents. None calls another. Each has a `where`
that says whether it needs the cloud.

| Agent | Where | Reads | Writes | v1? |
|---|---|---|---|---|
| Venue scorer | Cloud | past trips, loyalty by geo, online order ship-to, event calendar, weather | `venue_candidate` | Yes |
| Compliance checker | Cloud | `venue_candidate`, `ordinance`, `jurisdiction`, tax API, event vendor packet, field confirmations | `compliance_check`, `permit` in state `drafted` only | Yes, centerpiece |
| Research / inventory | Cloud, cut-down version on box | reviews, site searches by geo, wishlists, weather, event calendar, demand signals from past trips, optional social | `inventory_suggestion` | Yes, own-data only |
| Packing planner | Cloud | `venue_candidate`, `compliance_check`, `inventory_suggestion`, sales history | `pack_plan` | Yes |
| Clerk copilot | Box | packed products, allocations, compliance check | none, chat only | Yes |
| Upsell advisor | Tablet, offline | the basket, packed products with embeddings, allocations (only suggest what is in custody here), customer tier and past purchases where present, venue context (weather, event) | `upsell_suggestion` on the transaction, with accept/decline | Yes, Phase 1 |
| Evening / morning briefing | Box | day's transactions, demand signals, cached research pulls | `briefing` | Phase 1 |
| Reconciliation explainer | Cloud | allocations, transactions, exceptions for a trip | narrative on `trip` | Phase 2 |
| Trip retrospective | Cloud (draft on box) | everything for the trip | `retrospective` | Phase 2 |
| Returns adjudicator | Cloud | road transaction, venue return policy, condition note | proposal on `exception` | Phase 4 |
| Pricing proposer | Box | sales velocity, HQ price band | proposal doc, needs approval | Phase 4 |
| Fleet dispatcher | Cloud | all boxes, all trips | plan | Phase 4 |

### 6.0a Upsell advisor: hybrid search at checkout, on the tablet

When the clerk scans the second item into a basket, the tablet proposes one
or two add-ons. The proposal comes from a hybrid query in Couchbase Lite over
the packed catalog, with no network and under a second:

- **Vector side.** The basket's embedding (mean of the item embeddings, or the
  last-scanned item's) against the product vector index. "Goes with this."
- **Keyword and filter side.** Full-text and structured predicates in the same
  SQL++ statement: same category family or a complementary one, in stock in
  this custodian's allocation, price within a band of the basket, not already
  in the basket, matches the venue context (rain forecast boosts `waterproof`,
  cold boosts `insulated`). "Makes sense here."
- **Fusion.** Reciprocal rank fusion or a weighted blend of the two lists, done
  in the query or in a dozen lines of app code. The weight is a policy value so
  the demo can show it change.
- **Optional rerank by the small model** on the box when the box is up: a one
  line reason per suggestion ("rain tomorrow, you have a shell, not a hat").
  With the box down the suggestions still appear, without the reason.

Only items in custody on this tablet or the box are suggested, so the advisor
never recommends something the customer cannot walk away with. If the member's
record is on the tablet, prior purchases exclude repeats and tier can unlock a
bundle price. Each suggestion is written onto the transaction with
accept/decline, which is the eval signal and feeds the research agent's view of
what pairs well at this kind of venue.

**Demo beat.** Scan a rain shell. The tablet proposes a pack cover and wool
socks with a reason. Accept the socks. Then pull the box's power and scan
another shell: the same suggestions, no reason line. The query is the one to
put on screen, the way FieldProof shows its duplicate-check query.

### 6.1 Agent output contract

Every agent output is a document with: the inputs it read (doc ids), the model
and prompt version, a list of claims or recommendations each with evidence and
a status, and a `review` block the human fills in (accepted, rejected, edited,
by whom, when). The review block is the evaluation signal for every agent that
does not have a gold set.

### 6.2 Fencing

Agents propose. Humans or deterministic rules dispose. The packing agent does
not create allocations; accepting its plan does. The pricing agent does not
change prices; approving its proposal does. The compliance agent does not file
permits; it drafts them, and a back office moves them through every later
state (section 7.3a). This is a product stance and the demo states it once.

---

## 7. Compliance agent: evaluation and proof

The compliance agent is the centerpiece because it is the one where a confident
wrong answer costs real money. The demo shows it proving its work.

### 7.1 Pipeline

1. **Resolve jurisdiction** deterministically from lat/long: state, county,
   city, special tax districts. Hard filter for everything downstream.
2. **Retrieve** from `ordinance` with hybrid search: jurisdiction as a filter,
   semantic over the question ("temporary retail sales permit", "tent fire
   code", "sales tax registration transient vendor").
3. **Draft** the checklist: one claim per requirement with fee, lead time,
   where to apply, and the passage it came from.
4. **Ground check.** A second pass, different prompt and ideally a different
   model, takes each (claim, passage) pair and answers: does the passage
   support the claim? Yes, partially, no.
5. **Deterministic checks.** Freshness: is `retrieved_at` after the ordinance's
   `last_amended` where known? Jurisdiction: does the passage's jurisdiction
   equal the resolved one, by id not by name?
6. **Status.** Verified if all three pass. Needs confirmation if any one fails,
   naming which. Not found if retrieval returned nothing relevant, and the
   agent says so rather than guessing.
7. **Summary line** per site: "4 verified, 1 needs confirmation (tent rule:
   source older than last amendment), 0 not found. Feasible pending
   confirmation."

### 7.2 Demo beats

- Poison one chunk in `ordinance` before the demo (wrong fee, wrong
  jurisdiction label). Run the agent live. It flags the claim. Show why.
- Richmond, VA vs Richmond, CA: seed both. Show the jurisdiction check
  catching a name-matched retrieval.
- Click a verified claim on the tablet, offline. The passage, URL and date
  appear.

### 7.3 Human confirmation as data

When a clerk confirms a `needs_confirmation` item by calling the county, the
confirmation is written as a new `ordinance` document of type `confirmation`
with who, when, how and the answer. The agent treats it as a source on the
next run. The knowledge base improves per trip, and the confirmation can be
recorded on the box offline.

### 7.3a Permit flow: agent drafts, office vets, field confirms

The compliance checklist is the start of a workflow, not the end of one. A
back office (legal, operations, a store manager with the authority) vets what
the agent found, files what needs filing, and the result has to be on the
tablet when the inspector walks up. What the field learns has to make it back.
Each permit is one document with a state machine, synced in both directions
through the `trip:<trip-id>` channel, and every state change is a write by
whoever made it, wherever they were.

```
permit::<id>
{
  type: "permit",
  trip: "trip-2026-10-18-maker-fair",
  requirement: "transient vendor license",
  jurisdiction: "us-va-richmond-city",
  claim_ref: "compliance_check::<id>#claim-3",
  state: "drafted" | "vetting" | "needs_info" | "filed" | "approved"
         | "denied" | "waived" | "field_confirmed" | "inspected" | "flagged",
  history: [ { state, by, at, where: "cloud" | "box-07" | "tablet-B", note } ],
  attachments: [ "application.pdf", "approval.pdf", "inspection-photo.jpg" ],
  due: ..., filed_at: ..., approved_at: ..., expires: ...
}
```

**Cloud side.** The compliance agent writes one `permit` per requirement in
state `drafted`, with the filled application attached where it can produce
one. The back office works a queue of `drafted` permits: approve the agent's
reading and move to `filed`, ask a question (`needs_info`, with the question
in the note, routed back to the agent or to the field), decide the requirement
does not apply (`waived`, with the reason), or record the authority's answer
(`approved` with the approval PDF attached, or `denied`). The agent's
`needs_confirmation` claims land here too: the office either confirms from
its own knowledge or sends the question to the field.

**Edge side.** The box receives permits as they change. The compliance viewer
on the tablet shows each requirement with its state and the approval document
if there is one. The field can write three things back, all offline:

- `field_confirmed`: the clerk called the county from the parking lot, the
  answer is in the note, and it becomes a `confirmation` source for the agent
  (section 7.3).
- `inspected`: an inspector came by. Who, when, outcome, a photo of whatever
  they signed. Attached as blobs.
- `flagged`: something on the ground contradicts the paperwork. The organizer
  moved the booth into a different fire zone; the tent is bigger than the
  permit says. The note explains, and the back office sees it when the box
  phones home.

**Gating.** Policy decides what the box may do in each state. A venue with a
`denied` or still-`drafted` tax registration can be configured to block
`account` tender, or to block selling entirely, or to warn and proceed. The
gate is a policy document, not code, and the demo should show one being
flipped from HQ and taking effect on the tablet after the next sync.

**Who is the office?** The spec assumes an organization exists to vet. For the
demo, the back office is one screen in the Capella-side admin app with a queue
and three buttons. Say in the demo that the agent never moves a permit past
`drafted` on its own; everything from `vetting` onward is a human or the
authority. This is the fencing rule from section 6.2 applied to the one place
where it matters most.

**Demo beats.** With the cable in, the presenter approves a permit on the HQ
screen and attaches a PDF. Cable out. The approval is on the tablet. Inspector
moment: the assistant records an inspection with a photo, offline. Cable in.
The inspection appears in the HQ queue with the photo. Then flip the tender
gate from HQ and show tablet A honoring it after sync.

### 7.4 Gold set and eval runs

`gold_site` holds twenty sites with known-correct checklists. An eval run
executes the agent against all twenty and writes one `eval_run` document:
model, prompt version, claim-level precision and recall, count of false
`verified`, run time. A single chart over `eval_run` shows accuracy across
versions. False `verified` must be zero to ship a prompt change.

### 7.5 Sources

Ordinance text for v1 is seeded for three or four real jurisdictions from
public municipal code sites, with retrieval dates recorded. Tax rates come from
a tax API if one is available, otherwise a seeded table marked as such. The
demo is honest that the corpus is small; the architecture is what scales.

---

## 8. Couchbase Lite and sync showcase

Prioritized. The first five are in v1 and each gets a visible moment in the
demo.

1. **Custody, not counts, moved by scanning.** Section 4.1. The conservation
   query on screen while the tree is three deep.
2. **Pull the cable, keep selling.** Peer-to-peer plus live queries.
3. **Split the store and merge in any order.** Tablet B walks off with eight
   units and comes back; the phone splits off tablet B and comes back later.
   No coordinator, no cloud, both halves selling the whole time.
4. **Phone home lazily.** Every write is local and correct immediately;
   replication is continuous and opportunistic and never blocks. The cloud is
   informed, not consulted.
4a. **Credit as custody.** A loyalty member's offline allowance is reserved in
   the cloud, allocated to the box, split to tablets and enforced locally with
   a signed QR and no lookup. Pessimistic by policy, encrypted at rest, and
   still a real sale.
5. **Delta sync with a byte counter.** A day in kilobytes; a 10,000-SKU price
   change in a few hundred KB.
6. **Filtered replication.** Same product document, no cost or margin on the
   box. The copilot proving it does not have the data.
7. **Custom conflict resolver as app code.** Oversell becomes an exception
   with both sales, not a lost one. A double-scan becomes an exception, not a
   phantom unit.
8. **Revocation as purge.** Lost tablet drill.
9. **Checkpointed resume over a terrible link.** Throttle, cut, restore, show
   the checkpoint document.
10. **Blobs.** Permit PDF and product images sync like anything else.
11. **Clock skew tolerance.** One tablet deliberately wrong.
12. **Multi-hop.** Phone to tablet to box to cloud, conflict resolves
    identically three hops out.
13. **Document history on the box.** "What did inventory look like at 2pm",
    answered offline.
14. **Box-to-box custody transfer.** Two boxes in a parking lot, phase 4. Same
    gesture as a tablet split, one level up the tree.

---

## 9. Build plan

Suggested for a solo builder with an agentic coding setup. Each phase ends with
a working demo of everything so far.

| Phase | Deliverable | Rough effort |
|---|---|---|
| 0 | Skeleton: sync, custody, P2P, one staged conflict | 1 to 1.5 weeks |
| 1 | Edge AI: vector search, copilot, demand capture, compliance viewer | 1 week |
| 2 | Cloud AI: explainer, returns, retrospective, eventing | 1 week |
| 3 | Planning agents, compliance eval, Agent Catalog | 1.5 to 2 weeks |
| 4 | Stretch items as time allows | open |

Cut line for a first showing is the end of Phase 1 with a hand-written
compliance document and a scripted narration of what Phase 3 will do. The
cable-pull and the custody invariant carry a demo on their own.

### 9.1 Seed data

- Catalog: 300 to 500 SKUs across four or five categories, with images and
  precomputed embeddings. Outdoor apparel works well: rain, cold and heat all
  map to visible inventory decisions.
- Two stores, one region of loyalty customers (synthetic), eighteen months of
  synthetic sales with seasonality and three past pop-ups.
- Three or four real jurisdictions' ordinance text, chunked, with retrieval
  dates. One poisoned chunk kept aside for the demo.
- Twenty gold sites with hand-checked compliance answers.
- Event calendar and weather: static JSON for the demo weekend.

### 9.2 Hardware

Box: Raspberry Pi 5 with 8 GB, or any laptop. Tablets: two iPads or Android
tablets, a third for the kiosk if phase 4 happens. One phone running the same
app, for the second-level split. Printed QR labels on every demo unit, or on
a card per unit if the units are imaginary; scanning uses the device camera,
no dedicated scanner. A travel router or phone hotspot for the "terrible
link" mode. A physical switch or an obviously unplugged cable for beat 5; the
audience should see the cable come out.

---

## 10. Non-goals

- Real payment processing, PCI scope, receipt printing. Offline loyalty
  purchases are the retailer's own credit to known customers, bounded by
  policy; no card is ever authorized offline.
- Filing permits, registering for tax, or any legal action on the user's
  behalf.
- Social media ingestion beyond an optional, clearly labeled feed. The research
  agent is positioned on data the retailer already owns.
- Production-grade shrinkage detection. Suggestions with evidence only, never
  accusations, and not in v1.
- Multi-tenant or multi-retailer. One chain.

---

## 11. Open questions

- Which small model runs on the box, and does a Raspberry Pi 5 carry it at
  demo-acceptable latency, or does the box need to be a laptop for v1?
- Is a tax-rate API available for the demo account, or is the rate table
  seeded and labeled as such?
- Does the Edge Server to App Services path support the custom conflict
  resolver running in both places, or does the resolver live only on CBL and
  App Services? Confirm against current docs before Phase 0.
- Does Agent Catalog cover the on-box agents, or only the cloud ones? If only
  cloud, the on-box tool definitions are mirrored by hand and the spec says so.
- Which three or four jurisdictions seed the ordinance corpus? Pick ones with
  clear public municipal code and at least one that bans mobile retail in a
  zone, so the agent has something to kill.
- Who else at Couchbase has built on Edge Server recently, and is there a
  reference app to start from rather than a blank project?
- Naming: this spec says "Capella App Services" for the sync tier. If
  "Couchbase App Gateway" is the current or upcoming name for that tier or
  for a related component, swap the term everywhere before the page and deck
  go public. As of 2026-10-07 the public product page and docs use App
  Services.
- Peer discovery for splits: does the phone find tablet B over the CBL
  peer-to-peer listener on the venue wifi, or does the demo need a hotspot per
  node? Decide before Phase 0 because it shapes how the split is staged on
  stage.
- Signed loyalty QR: who holds the signing key and how is it rotated? For the
  demo a single retailer key pair is fine, with the public key synced as a
  document; note that production would rotate and the box would need the
  current and previous key.
- Confirm the Couchbase Lite database encryption story on each tablet platform
  the demo uses, and how the box vends the key at pairing (QR shown on the box
  screen is probably enough for a demo).
- Unit-level or case-level QR? Unit-level makes the demo more tactile and the
  double-scan exception more obvious. Case-level is closer to how real retail
  packs. Probably unit-level for the demo with a note that the model handles
  both.

---

## 12. Demo runbook (sketch)

Pre-flight: box charged and synced, two tablets at 100%, one tablet's clock
set wrong, poisoned chunk in place, staged HQ sale queued, byte counter reset,
cable visible.

1. Open on the venue scorer's five candidates. Thirty seconds.
2. Run the compliance checker live. Point at the flagged claim and the
   poisoned source. Ninety seconds.
3. Research suggestions, accept two. Packing plan, approve. Watch the box
   fill. On the HQ screen, approve the tent permit and attach the PDF. Two
   minutes.
4. Pull the cable. Sell on both tablets by scanning. Point at live counts.
   Ninety seconds.
5. Copilot question. Upsell at checkout with the hybrid query on screen, then
   again with the box powered off. Demand capture with voice. Loyalty member buys on
   account offline, then gets declined at tablet B for the remainder. Fire
   marshal moment: permit on the tablet, inspection recorded with a photo.
   Two minutes.
6. Split. Assistant scans eight jackets onto tablet B and walks to the back of
   the room. Both keep selling. Assistant scans three onto a phone and hands it
   to someone in the audience. Phone sells one. Phone comes back to tablet B,
   tablet B comes back to the box. Counts agree. Say "nobody asked the cloud."
   Two minutes.
7. Fire the staged HQ sale. Plug the cable in. Byte counter. Conservation
   query across store, box, tablet B and phone. Inspection record appears in
   the HQ queue. Exception appears with the drafted customer message. Two
   minutes.
8. Retrospective. Scroll to its three recommendations. Point back at the
   venue scorer. One minute.
9. Close: cloud picks the destination, edge runs the day, database is the
   message bus, and the store can divide and merge without stopping. Same
   pattern for cruise ships, mobile clinics, field service vans, stadium
   concessions. Thirty seconds.
