// Every golden case in contracts/fixtures/sync/ is one test.
import assert from "node:assert/strict";
import { test } from "node:test";

import { functionFor, loadCases, runSync } from "./harness.mjs";

const cases = loadCases();

test("there are sync fixture cases to run", () => {
  assert.ok(cases.length > 0);
});

for (const c of cases) {
  test(`${c.collection}: ${c.name}`, () => {
    const result = runSync(functionFor(c.collection), { user: c.user, doc: c.doc, oldDoc: c.oldDoc });
    if (c.expect.ok) {
      assert.equal(result.ok, true, `rejected: ${result.error}`);
      assert.deepEqual(result.channels, [...c.expect.channels].sort());
    } else {
      assert.equal(result.ok, false, `accepted, routed to ${JSON.stringify(result.channels)}`);
      assert.ok(result.error.includes(c.expect.error), `error "${result.error}" lacks "${c.expect.error}"`);
    }
  });
}
