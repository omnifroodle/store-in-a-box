// `node --test sync/tests/` (CI): Node 22 runs the directory as one module, which resolves to this file, so it loads
// every *.test.mjs here. Node 23 and later expand the directory themselves and do not run this file (its name matches
// no test pattern). Either way each test file runs once.
"use strict";
const { readdirSync } = require("node:fs");
const { join } = require("node:path");
const { pathToFileURL } = require("node:url");

(async () => {
  for (const f of readdirSync(__dirname).filter((n) => n.endsWith(".test.mjs")).sort()) {
    await import(pathToFileURL(join(__dirname, f)).href);
  }
})();
