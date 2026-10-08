function (doc, oldDoc, meta) {
  // retail.store.allocation: a box writes its own trip's allocations; later only status and closed_at change.
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
  if (doc.type !== "allocation") throw({forbidden: "type mismatch"});
  if (!doc.trip) throw({forbidden: "trip is required"});
  if (!doc.box && !isUser("hq")) throw({forbidden: "box is required"});
  if (!isUser(doc.box ? [doc.box, "hq"] : "hq")) throw({forbidden: "a box writes only its own documents"});
  requireAccess("trip:" + doc.trip);
  if (oldDoc && !oldDoc._deleted && changedExcept(["status", "closed_at"])) {
    throw({forbidden: "only status and closed_at may change"});
  }
  channel("trip:" + doc.trip);
}
