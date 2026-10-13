// A fake of the App Services sync-function runtime, enough to run sync/functions/*.js against
// contracts/fixtures/sync/. It mirrors Sync Gateway's built-ins: requireUser, requireAccess and requireRole throw
// {forbidden} for a user who fails them and pass in the admin context (user null: an import or an admin write);
// a user holding "*" has access to every channel.
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const FUNCTIONS_DIR = join(ROOT, "sync", "functions");
export const SYNC_FIXTURES_DIR = join(ROOT, "contracts", "fixtures", "sync");

const BUILTINS = ["channel", "access", "role", "expiry", "requireUser", "requireAccess", "requireRole", "requireAdmin"];

// Compile a function file (one `function (doc, oldDoc, meta) { ... }` expression, as pasted into App Services).
export function loadSyncFunction(path) {
  const source = readFileSync(path, "utf8");
  const make = new Function(...BUILTINS, `"use strict";\nreturn (${source});`);
  return { path, source, make };
}

export function functionFor(collection) {
  return loadSyncFunction(join(FUNCTIONS_DIR, `store.${collection}.js`));
}

// Sync Gateway's makeArray (channels/sync_runner.go): an array as it is, anything else wrapped. Never flattened, so
// requireUser([["box-07"], "hq"]) refuses box-07 there and here.
const makeArray = (x) => (Array.isArray(x) ? x : [x]);
// channel() and access() arguments (ottoValueToStringArray, base.ValueToStringArray): a string or an array of
// strings; anything else, a nested array included, is ignored (Sync Gateway logs a warning).
const strings = (x) => makeArray(x).filter((v) => typeof v === "string");

// Run a loaded function as `user` ({name, channels, roles?}, or null for the admin context).
// Returns {ok: true, channels, access} or {ok: false, error}.
export function runSync(fn, { user, doc, oldDoc = null, meta = { xattrs: {} } }) {
  const channels = new Set();
  const grants = [];
  const builtins = {
    channel: (...args) => args.flatMap(strings).forEach((c) => channels.add(c)),
    access: (users, chans) => grants.push({ users: strings(users), channels: strings(chans) }),
    role: () => {},
    expiry: () => {},
    requireUser: (names) => {
      if (user && makeArray(names).indexOf(user.name) === -1) throw { forbidden: "wrong user" };
    },
    requireAccess: (chans) => {
      if (!user) return;
      const held = user.channels || [];
      // "*" passing requireAccess is an assumption: Sync Gateway's requireAccess compares the user's channel names
      // with no special case for "*" (checked on the real runtime by issue #40).
      if (!held.includes("*") && !makeArray(chans).some((c) => held.indexOf(c) !== -1)) {
        throw { forbidden: "missing channel access" };
      }
    },
    requireRole: (roles) => {
      if (user && !makeArray(roles).some((r) => (user.roles || []).indexOf(r) !== -1)) {
        throw { forbidden: "missing role" };
      }
    },
    requireAdmin: () => {
      if (user) throw { forbidden: "sgw admin required" };
    },
  };
  const sync = fn.make(...BUILTINS.map((b) => builtins[b]));
  try {
    sync(structuredClone(doc), oldDoc === null ? null : structuredClone(oldDoc), meta);
  } catch (e) {
    if (e && typeof e === "object" && (e.forbidden || e.unauthorized)) {
      return { ok: false, error: e.forbidden || e.unauthorized };
    }
    throw e; // anything else is a bug in the function, not a rejection
  }
  return { ok: true, channels: [...channels].sort(), access: grants };
}

export function loadCases(dir = SYNC_FIXTURES_DIR) {
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => JSON.parse(readFileSync(join(dir, f), "utf8")));
}
