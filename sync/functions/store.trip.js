function (doc, oldDoc, meta) {
  // retail.store.trip: only HQ writes a trip; it reaches the trip's channel and its box's channel.
  function isUser(names) {
    try { requireUser(names); return true; } catch (e) { return false; }
  }
  function routes(d) {
    return d && d.trip_id ? ["trip:" + d.trip_id, "box:" + d.box] : [];
  }

  if (doc._deleted) {
    if (!isUser("hq")) throw({forbidden: "deletes are hq only"});
    channel(routes(oldDoc));
    return;
  }
  if (doc.type !== "trip") throw({forbidden: "type mismatch"});
  if (!doc.trip_id) throw({forbidden: "trip is required"});
  if (!doc.box) throw({forbidden: "box is required"});
  if (!isUser("hq")) throw({forbidden: "writer must be hq"});
  channel(routes(doc));
}
