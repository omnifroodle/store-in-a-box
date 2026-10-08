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

const list = (x) => (Array.isArray(x) ? x.flat(Infinity) : [x]).filter((v) => v !== null && v !== undefined);

// Run a loaded function as `user` ({name, channels, roles?}, or null for the admin context).
// Returns {ok: true, channels, access} or {ok: false, error}.
export function runSync(fn, { user, doc, oldDoc = null, meta = { xattrs: {} } }) {
  const channels = new Set();
  const grants = [];
  const builtins = {
    channel: (...names) => list(names).forEach((c) => channels.add(c)),
    access: (users, chans) => grants.push({ users: list(users), channels: list(chans) }),
    role: () => {},
    expiry: () => {},
    requireUser: (names) => {
      if (user && !list(names).includes(user.name)) throw { forbidden: "wrong user" };
    },
    requireAccess: (chans) => {
      if (!user) return;
      const held = user.channels || [];
      if (!held.includes("*") && !list(chans).some((c) => held.includes(c))) {
        throw { forbidden: "missing channel access" };
      }
    },
    requireRole: (roles) => {
      if (user && !list(roles).some((r) => (user.roles || []).includes(r))) throw { forbidden: "missing role" };
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
