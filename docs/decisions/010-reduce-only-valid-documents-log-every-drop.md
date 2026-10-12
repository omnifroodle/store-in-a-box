# 010: A node reduces only schema-valid documents, drops the rest, and logs every drop

Status: accepted (owner, 2026-10-12). Issues: #96, #104 item 4.

The Swift ledger (WS4) and the Python reference (WS1) agree on every schema-valid document and differ on invalid
ones: an extra field in a rule-5 tie-break, a resolution missing `at`, `note` or `by`, a transaction missing a required
field (#96). Invalid documents can reach a tablet because the App Services sync function guards only the Capella path;
device-to-device sync and the box (Edge Server 1.1 has no per-collection privileges, #50) never run it. Separately,
`CustodyStore.all()` skips an undecodable document with `try?` and the conservation row can still say `holds` (#104
item 4).

1. **The choice.** The reducer's input is documents that pass their collection's schema (including the rules the
   validator checks, `contracts/README.md`). A node that finds a document failing its schema does not reduce it, and
   it does not stop reducing either: it drops the document. **Every drop is recorded**: the document id, the
   collection, why it failed, where it came from when the node knows (a peer, the box, Capella) and when. No node
   skips a document silently (the Swift `try?`) or raises (the Python `KeyError`). The drops are counted beside the
   conservation result, and a conservation row computed with drops is never shown as a plain `HOLDS`: it says how
   many documents were dropped. The same rule applies in Python and Swift, so both ports are right on the three
   cases in #96; most of them cannot arise at all, because every transaction and exception schema has
   `additionalProperties: false`. Rejected: pinning each divergent behaviour with a fixture (it makes Swift carry raw
   JSON through the reducer and fixes accidents, such as Python reading a missing `resolution.hlc` as `""`, as
   contract); and leaving it (the ports would disagree on stage the first time a bad document arrives).
2. **What it costs.** A schema pre-filter in the Python reference; a drop record and its surfacing (Diagnostics on
   the tablet, the HQ report) that did not exist; a new field in the conservation result and a fixture format that can
   carry invalid input; a dropped document may be a real movement (a device on a newer schema, a bug), and then the
   ledger shows a hole instead of the movement, which is why the drop is counted beside `holds`. Drops are about
   visibility, not repair.
3. **When to revisit.** When the documents' `v` is ever raised (an older node would drop every newer document), when
   Phase 2's close makes a dropped document a settlement question, or if drop counts show up in a rehearsal.

Contract change: version 0.7.0 (a changed reducer rule, `contracts/README.md` "Versioning"), applied by the foreman as
CC11 after the architect has designed the drop record and the fixture format. Nothing is dispatched until then.
