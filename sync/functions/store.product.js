function (doc, oldDoc, meta) {
  // retail.store.product: only HQ writes the catalog; a product reaches each of its regions' catalogs.
  function isUser(names) {
    try { requireUser(names); return true; } catch (e) { return false; }
  }
  function catalogs(d) {
    return (d && d.regions || []).map(function (r) { return "catalog:" + r; });
  }

  if (doc._deleted) {
    if (!isUser("hq")) throw({forbidden: "deletes are hq only"});
    channel(catalogs(oldDoc));
    return;
  }
  if (doc.type !== "product") throw({forbidden: "type mismatch"});
  if (!isUser("hq")) throw({forbidden: "writer must be hq"});
  if (!Array.isArray(doc.regions) || doc.regions.length === 0) throw({forbidden: "regions is required"});
  channel(catalogs(doc));
}
