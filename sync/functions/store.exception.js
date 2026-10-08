function (doc, oldDoc, meta) {
  // retail.store.exception: a box reports open exceptions for its trip; only HQ resolves them.
  function isUser(names) {
    try { requireUser(names); return true; } catch (e) { return false; }
  }
  function same(a, b) {
    if (a === b) return true;
    if (!a || !b || typeof a !== "object" || typeof b !== "object") return false;
    if (Array.isArray(a) !== Array.isArray(b) || Object.keys(a).length !== Object.keys(b).length) return false;
    return Object.keys(a).every(function (k) { return b.hasOwnProperty(k) && same(a[k], b[k]); });
  }
  function changedExcept(allowed) {
    return Object.keys(doc).concat(Object.keys(oldDoc)).some(function (k) {
      return k.charAt(0) !== "_" && allowed.indexOf(k) < 0 && !same(doc[k], oldDoc[k]);
    });
  }

  if (doc._deleted) {
    if (!isUser("hq")) throw({forbidden: "deletes are hq only"});
    if (oldDoc && oldDoc.trip) channel("trip:" + oldDoc.trip);
    return;
  }
  if (doc.type !== "exception") throw({forbidden: "type mismatch"});
  if (!doc.trip) throw({forbidden: "trip is required"});
  if (!doc.box && !isUser("hq")) throw({forbidden: "box is required"});
  if (!isUser(doc.box ? [doc.box, "hq"] : "hq")) throw({forbidden: "a box writes only its own documents"});
  requireAccess("trip:" + doc.trip);
  var update = oldDoc && !oldDoc._deleted;
  if (!isUser("hq") && (update || doc.status !== "open")) throw({forbidden: "only hq may resolve"});
  if (update && changedExcept(["status", "resolution"])) {
    throw({forbidden: "only status and resolution may change"});
  }
  channel("trip:" + doc.trip);
}
