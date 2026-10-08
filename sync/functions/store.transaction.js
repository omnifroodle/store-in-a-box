function (doc, oldDoc, meta) {
  // retail.store.transaction: a box writes its own trip's movements; a movement never changes once written.
  function isUser(names) {
    try { requireUser(names); return true; } catch (e) { return false; }
  }

  if (doc._deleted) {
    if (!isUser("hq")) throw({forbidden: "deletes are hq only"});
    if (oldDoc && oldDoc.trip) channel("trip:" + oldDoc.trip);
    return;
  }
  if (doc.type !== "transaction") throw({forbidden: "type mismatch"});
  if (!doc.trip) throw({forbidden: "trip is required"});
  if (!doc.box && !isUser("hq")) throw({forbidden: "box is required"});
  if (!isUser(doc.box ? [doc.box, "hq"] : "hq")) throw({forbidden: "a box writes only its own documents"});
  requireAccess("trip:" + doc.trip);
  if (oldDoc && !oldDoc._deleted) throw({forbidden: "immutable"});
  channel("trip:" + doc.trip);
}
