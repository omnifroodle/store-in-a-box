// Rules from docs/workstreams/WS2-capella-sync.md that the golden fixtures do not pin down, and the harness itself.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { FUNCTIONS_DIR, functionFor, loadCases, runSync } from "./harness.mjs";

const BOX = { name: "box-07", channels: ["trip:trip-2026-10-18-riverfest", "catalog:va-central", "box:box-07"] };
const HQ = { name: "hq", channels: ["*"] };
const ADMIN = null; // an import or an admin write: no user context
const byName = Object.fromEntries(loadCases().map((c) => [c.name, c]));
const fixture = (name) => structuredClone(byName[name]);
const run = (collection, user, doc, oldDoc = null) => runSync(functionFor(collection), { user, doc, oldDoc });

test("each function file is one ES5 function expression (App Services runs ES5)", () => {
  const files = readdirSync(FUNCTIONS_DIR).filter((f) => f.endsWith(".js")).sort();
  assert.deepEqual(files, ["store.allocation.js", "store.exception.js", "store.product.js", "store.transaction.js",
    "store.trip.js"]);
  for (const f of files) {
    const src = readFileSync(join(FUNCTIONS_DIR, f), "utf8");
    assert.match(src, /^function \(doc, oldDoc, meta\) \{\n[\s\S]*\n\}\n$/, f);
    for (const bad of [/=>/, /\blet\b/, /\bconst\b/, /`/, /\.includes\(/, /\bclass\b/]) {
      assert.doesNotMatch(src, bad, `${f} uses ${bad}`);
    }
    assert.ok(src.split("\n").length <= 40, `${f} is too long to put on screen`);
  }
});

test("the admin context (an import) passes the writer and access checks", () => {
  const c = fixture("transaction-by-box-ok");
  assert.deepEqual(run("transaction", ADMIN, c.doc), { ok: true, channels: [c.expect.channels[0]], access: [] });
});

test("an update over a tombstone is a create (a reset trip's ids may come back)", () => {
  const c = fixture("transaction-by-box-ok");
  const result = run("transaction", BOX, c.doc, { _id: c.doc._id, _deleted: true });
  assert.equal(result.ok, true, result.error);
});

test("transactions are immutable for hq too", () => {
  const c = fixture("transaction-update-forbidden");
  assert.equal(run("transaction", HQ, c.doc, c.oldDoc).error, "immutable");
});

test("rewriting an allocation into this box is caught by the update rule", () => {
  const c = fixture("allocation-close-ok");
  const old = { ...c.oldDoc, box: "box-08" };
  assert.equal(run("allocation", BOX, c.doc, old).error, "only status and closed_at may change");
});

test("hq may not change an allocation's sku either", () => {
  const c = fixture("allocation-change-sku-forbidden");
  assert.equal(run("allocation", HQ, c.doc, c.oldDoc).error, "only status and closed_at may change");
});

test("an unchanged rewrite of an allocation is accepted (field order does not matter)", () => {
  const c = fixture("allocation-close-ok");
  const reordered = Object.fromEntries(Object.entries(c.doc).reverse());
  assert.equal(run("allocation", BOX, reordered, c.doc).ok, true);
});

test("a box may not create an exception for another box", () => {
  const c = fixture("exception-create-by-box-ok");
  assert.equal(run("exception", BOX, { ...c.doc, box: "box-08" }).error, "a box writes only its own documents");
});

test("a box without the trip channel cannot write a transaction", () => {
  const c = fixture("transaction-by-box-ok");
  assert.match(run("transaction", { name: "box-07", channels: ["box:box-07"] }, c.doc).error, /access/);
});

test("a delete is checked before the type: box-07 deleting a product is refused as a delete", () => {
  const c = fixture("product-by-hq-ok");
  assert.equal(run("product", BOX, { _id: c.doc._id, _deleted: true }, c.doc).error, "deletes are hq only");
});

test("hq deleting a product routes the tombstone to every old region", () => {
  const c = fixture("product-two-regions");
  const result = run("product", HQ, { _id: c.doc._id, _deleted: true }, c.doc);
  assert.deepEqual(result.channels, ["catalog:va-central", "catalog:va-tidewater"]);
});

test("hq deleting a trip routes the tombstone to the trip and its box", () => {
  const c = fixture("trip-by-hq-ok");
  const result = run("trip", HQ, { _id: c.doc._id, _deleted: true }, c.doc);
  assert.deepEqual(result.channels, ["box:box-07", "trip:trip-2026-10-18-riverfest"]);
});

test("a delete with no old document routes nowhere and does not throw", () => {
  for (const coll of ["product", "trip", "allocation", "transaction", "exception"]) {
    assert.deepEqual(run(coll, HQ, { _id: "x", _deleted: true }).channels, [], coll);
  }
});

test("a product needs at least one region", () => {
  const c = fixture("product-by-hq-ok");
  assert.equal(run("product", HQ, { ...c.doc, regions: [] }).ok, false);
  assert.equal(run("product", HQ, { ...c.doc, regions: undefined }).ok, false);
});

test("the harness surfaces a function bug instead of reporting a rejection", () => {
  const broken = { make: () => () => { throw new TypeError("boom"); } };
  assert.throws(() => runSync(broken, { user: HQ, doc: { _id: "x" } }), TypeError);
});
