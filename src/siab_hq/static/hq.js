// The HQ screen: polls the server's panels every 2 s and posts the presenter's actions. No build step.
// The server renders every word on screen (/panels/<name>); this file only fetches, places and posts.
"use strict";

const PANELS = ["conservation", "tree", "exceptions", "stage", "box"];
const trip = new URLSearchParams(location.search).get("trip") || "";
const last = {};

function query(extra) {
  const p = new URLSearchParams(extra || {});
  if (trip) p.set("trip", trip);
  return "?" + p.toString();
}

function showError(message) {
  document.getElementById("error").textContent = message || "";
}

async function refresh(name) {
  const el = document.getElementById(name);
  if (el.contains(document.activeElement) && document.activeElement !== document.body) return; // typing a note
  const extra = name === "exceptions" ? { status: document.getElementById("status").value } : {};
  const r = await fetch("/panels/" + name + query(extra));
  const html = await r.text();
  if (!r.ok) throw new Error(name + ": " + html);
  if (last[name] === html) return;
  const select = el.querySelector("select");
  const kept = select ? select.value : null;
  el.innerHTML = html;
  last[name] = html;
  const fresh = el.querySelector("select");
  if (fresh && kept && [...fresh.options].some((o) => o.value === kept)) fresh.value = kept;
}

async function refreshAll() {
  try {
    for (const name of PANELS) await refresh(name);
    showError("");
  } catch (e) {
    showError(String(e.message || e));
  }
}

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ trip: trip || undefined }, body)),
  });
  const reply = await r.json();
  if (!r.ok) throw new Error(reply.error || r.statusText);
  return reply;
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  event.preventDefault();
  try {
    if (button.dataset.action === "resolve") {
      const dispute = button.closest("[data-dispute-key]");
      const note = dispute.querySelector("input.note");
      await post("/api/exceptions/resolve", {
        dispute_key: dispute.dataset.disputeKey,
        transactions: JSON.parse(dispute.dataset.transactions),
        chosen_txn: button.dataset.chosen || null,
        note: note ? note.value : "",
      });
    } else if (button.dataset.action === "close-superseded") {
      await post("/api/exceptions/close-superseded", {});
    }
    document.activeElement.blur();
    await refreshAll();
  } catch (e) {
    showError(String(e.message || e));
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("form[data-action=stage]");
  if (!form) return;
  event.preventDefault();
  try {
    await post("/api/stage/hq-sale", { unit_id: form.elements.unit_id.value });
    document.activeElement.blur();
    await refreshAll();
  } catch (e) {
    showError(String(e.message || e));
  }
});

document.getElementById("status").addEventListener("change", () => {
  delete last.exceptions;
  refreshAll();
});

refreshAll();
setInterval(refreshAll, 2000);
