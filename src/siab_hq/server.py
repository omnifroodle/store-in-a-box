"""The HQ screen's HTTP API (``ports/hq.md``) and its panels. Plain asyncio, one request per connection, loopback only.

The JSON endpoints are the API; ``/panels/<name>`` are the same views rendered as HTML fragments, which the screen's
one JS file polls every 2 s and drops in place. The screen's words (the reason a row fails, the ``holds`` indicator,
a dispute's label) are rendered here, once, so the tests read what the presenter sees.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from siab_capella.provision import ks
from siab_ledger import conservation

from .queries import TripNotFound
from .reconcile import FORK_KINDS, BadRequest, Hq, NotFound, Snapshot, queue, stageable

Response = tuple[int, str, bytes]
REASONS = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error",
           502: "Bad Gateway"}
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/hq.js": ("hq.js", "text/javascript; charset=utf-8"),
          "/hq.css": ("hq.css", "text/css; charset=utf-8")}
LIVE_HEADER = "trip open: live view, nothing settled"
MAX_BODY = 64 * 1024


def _http_get(url: str) -> Any:
    return httpx.get(url, timeout=2.0).json()


@dataclass
class App:
    hq: Hq
    box_status_url: str = ""
    http_get: Callable[[str], Any] = _http_get
    _names: dict[str, str | None] = field(default_factory=dict)

    def product_name(self, sku: str) -> str | None:
        if sku not in self._names:
            self._names[sku] = (self.hq.gw.get(ks("product"), f"product::{sku}") or {}).get("name")
        return self._names[sku]


# ---------------------------------------------------------------- views (JSON)

def reason(row: dict) -> str:
    """Why a conservation row does not hold, as the screen says it; empty when it holds."""
    parts = []
    if row["store_on_hand"] is not None and row["store_on_hand"] < 0:
        parts.append(f"overdrawn by {-row['store_on_hand']}")
    if row["untraced"] > 0:
        parts.append(f"{row['untraced']} untraced")
    return ", ".join(parts)


def indicator(rows: list[dict]) -> str:
    failing = sum(1 for r in rows if not r["holds"])
    return "HOLDS · live" if failing == 0 else f"{failing} SKUs do not hold · live"


def conservation_view(snap: Snapshot, *, sql: bool = False) -> dict:
    rows = [r.to_json() for r in conservation(snap.state, snap.data.store, snap.data.inventory)]
    out = {"trip": snap.data.trip, "as_of": snap.as_of, "rows": rows, "holds": all(r["holds"] for r in rows)}
    if sql:
        out["statements"] = snap.data.statements
    return out


def tree_view(snap: Snapshot) -> dict:
    """The custody tree: the store, then each custodian under the one it took its allocation from."""
    state, data = snap.state, snap.data
    store, trip = data.store, data.trip_doc
    docs = {a["_id"]: a for a in data.allocations}
    opened_by_txn: dict[str, dict] = {}
    for t in sorted(state.transactions.values(), key=lambda t: (t["hlc"], t["_id"])):
        if t["to_allocation"] is not None:
            opened_by_txn.setdefault(t["to_allocation"], t)
    allocations: dict[str, list[dict]] = {}
    parents: dict[str, str] = {}
    for aid in sorted(set(state.allocation_counts) | set(docs)):
        doc, txn = docs.get(aid), opened_by_txn.get(aid)
        custodian = doc["custodian"] if doc else txn["to_custodian"] if txn else None
        if custodian is None:
            continue
        allocations.setdefault(custodian, []).append({
            "id": aid,
            "sku": doc["sku"] if doc else txn["sku"],
            "status": doc["status"] if doc else None,
            "count": state.allocation_counts.get(aid, 0),
        })
        parents.setdefault(custodian, doc["from_custodian"] if doc else txn["from_custodian"])
    held: dict[str, dict[str, int]] = {}
    for (custodian, sku), n in sorted(state.counts.items()):
        if n >= 1:
            held.setdefault(custodian, {})[sku] = n
    custodians = {store, *allocations, *held}

    def parent(c: str) -> str | None:
        if c == store:
            return None
        if c in parents and parents[c] in custodians and parents[c] != c:
            return parents[c]
        if c in trip.get("devices", ()) and trip.get("box") in custodians:
            return trip["box"]
        return store

    kids: dict[str | None, list[str]] = {}
    for c in sorted(custodians):
        kids.setdefault(parent(c), []).append(c)
    order, todo, seen = [], deque([store]), set()
    while todo:
        c = todo.popleft()
        if c in seen:
            continue
        seen.add(c)
        order.append(c)
        todo.extend(kids.get(c, ()))
    order += sorted(custodians - seen)  # a parent cycle in the data: still shown, under nothing
    nodes = [{"custodian": c, "parent": parent(c), "allocations": allocations.get(c, []), "held": held.get(c, {})}
             for c in order]
    return {"root": store, "nodes": nodes}


def exceptions_view(snap: Snapshot, status: str) -> dict:
    return queue(snap.state, snap.data.exceptions, status)


def box_view(app: App) -> tuple[int, dict]:
    if not app.box_status_url:
        return 200, {"configured": False}
    try:
        return 200, app.http_get(app.box_status_url)
    except Exception as e:  # noqa: BLE001 (any failure to reach the box is the panel's news, not a crash)
        return 502, {"configured": True, "reachable": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- panels (HTML fragments)

def _short(txn_id: str) -> str:
    return txn_id.removeprefix("txn::")


def conservation_panel(app: App, snap: Snapshot) -> str:
    view = conservation_view(snap)
    holds = view["holds"]
    out = [f'<header><h2>Conservation</h2><p class="live">{LIVE_HEADER}</p>'
           f'<p class="indicator {"holds" if holds else "fails"}">{escape(indicator(view["rows"]))}</p></header>',
           "<table><thead><tr><th>SKU</th><th>Opening</th><th>Received</th><th>Left store</th><th>Returned</th>"
           "<th>Store on hand</th><th>In custody</th><th>Sold</th><th>Disputed</th><th>Untraced</th><th>Holds</th>"
           "<th>Reason</th></tr></thead><tbody>"]
    for r in view["rows"]:
        name = app.product_name(r["sku"])
        custody = ", ".join(f"{escape(c)} {n}" for c, n in r["in_custody"].items())
        cells = [f'<td class="sku">{escape(r["sku"])}' + (f'<small>{escape(name)}</small>' if name else "") + "</td>"]
        cells += [f'<td class="n">{r[k]}</td>' for k in ("opening_on_hand", "received", "left_store",
                                                         "returned_to_store", "store_on_hand")]
        cells.append(f"<td>{custody}</td>")
        cells += [f'<td class="n">{r[k]}</td>' for k in ("sold", "disputed", "untraced")]
        cells.append(f'<td>{"yes" if r["holds"] else "no"}</td><td class="reason">{escape(reason(r))}</td>')
        out.append(f'<tr class="{"" if r["holds"] else "fail"}">{"".join(cells)}</tr>')
    out.append(f'</tbody></table><p class="as-of">as of {escape(view["as_of"])}</p>')
    return "".join(out)


def tree_panel(snap: Snapshot) -> str:
    view = tree_view(snap)
    kids: dict[str | None, list[dict]] = {}
    for n in view["nodes"]:
        kids.setdefault(n["parent"], []).append(n)

    def node(n: dict) -> str:
        held = ", ".join(f"{escape(s)} {q}" for s, q in n["held"].items()) or "nothing held"
        allocs = "".join(f'<li class="alloc">{escape(a["sku"])} <b>{a["count"]}</b> '
                         f'<small>{escape(a["id"])} {escape(a["status"] or "")}</small></li>'
                         for a in n["allocations"])
        sub = "".join(node(k) for k in kids.get(n["custodian"], ()))
        return (f'<li><span class="custodian">{escape(n["custodian"])}</span> <small>{held}</small>'
                f'<ul>{allocs}{sub}</ul></li>')

    roots = [n for n in view["nodes"] if n["parent"] is None]
    return '<header><h2>Custody</h2></header><ul class="tree">' + "".join(node(n) for n in roots) + "</ul>"


def _movement(t: dict) -> str:
    return (f'{escape(t["device"])} {escape(t["kind"])} {escape(t["from_custodian"])} &rarr; '
            f'{escape(t["to_custodian"])} <small>{escape(_short(t["_id"]))}</small>')


def exceptions_panel(snap: Snapshot, status: str) -> str:
    view = exceptions_view(snap, status)
    out = ['<header><h2>Exceptions</h2></header>']
    if not view["disputes"]:
        out.append(f'<p class="empty">no {escape(status if status != "all" else "")} disputes</p>')
    for e in view["disputes"]:
        attrs = (f'data-dispute-key="{escape(e["dispute_key"])}" '
                 f'data-transactions="{escape(json.dumps([t["_id"] for t in e["transactions"]]))}"')
        detectors = ", ".join(e["detectors"]) or "none yet"
        out.append(f'<article class="dispute {escape(e["status"])}" {attrs}><h3>{escape(e["kind"])} '
                   f'{escape(e["unit_id"])} <span class="label">{escape(e["label"])}</span></h3>'
                   f'<p class="detectors">detected by {escape(detectors)}</p><ul>')
        fork = e["kind"] in FORK_KINDS
        for b in e["branches"]:
            t, lf = b["txn"], b["leaf"]
            line = _movement(t)
            if lf["_id"] != t["_id"]:
                line += f'<br><span class="leaf">leaf: {_movement(lf)}</span>'
            if not fork and t["_id"] != e["dispute_key"].partition("|")[2]:
                line = f'<span class="pred">before it: {line}</span>'
            button = ""
            if fork and e["status"] == "open":
                button = (f' <button data-action="resolve" data-chosen="{escape(t["_id"])}">'
                          f'choose {escape(t["device"])}</button>')
            out.append(f"<li>{line}{button}</li>")
        out.append("</ul>")
        if not fork:
            out.append('<p class="why">did not hold it</p>')
        if e["status"] == "open":
            out.append('<input class="note" placeholder="note" aria-label="note">')
            if not fork:
                out.append('<button data-action="resolve" data-chosen="">close</button>')
        elif e["resolution"]:
            r = e["resolution"]
            chosen = _short(r["chosen_txn"]) if r["chosen_txn"] else "nothing"
            out.append(f'<p class="resolution">chose {escape(chosen)} at {escape(r["at"])}: {escape(r["note"])}</p>')
        out.append("</article>")
    if view["superseded"]:
        out.append(f'<section class="superseded"><h3>superseded ({len(view["superseded"])})</h3><ul>')
        out += [f'<li>{escape(d["_id"])}</li>' for d in view["superseded"]]
        out.append('</ul><button data-action="close-superseded">close superseded</button></section>')
    return "".join(out)


def stage_panel(snap: Snapshot) -> str:
    units = stageable(snap.state, snap.data.trip_doc)
    options = "".join(f'<option value="{escape(u["unit_id"])}">{escape(u["unit_id"])} on {escape(u["holder"])}'
                      "</option>" for u in units)
    disabled = "" if units else " disabled"
    return ('<header><h2>Stage the HQ oversell</h2></header><form data-action="stage">'
            f'<select name="unit_id" aria-label="unit"{disabled}>{options}</select>'
            f'<button type="submit"{disabled}>sell at the flagship</button></form>')


def box_panel(app: App) -> str:
    status, body = box_view(app)
    if not body.get("configured", True):
        return '<header><h2>Box</h2></header><p class="empty">box not configured (SIAB_BOX_STATUS_URL)</p>'
    if status != 200:
        return f'<header><h2>Box</h2></header><p class="fails">box unreachable: {escape(body["error"])}</p>'
    up, b = body.get("uplink") or {}, body.get("bytes") or {}
    state = "CUT" if up.get("cut") else ("up" if up.get("reachable") else "unreachable")
    return (f'<header><h2>Box {escape(str(body.get("box", "")))}</h2></header>'
            f'<p class="bytes">out {b.get("out", 0):,} B &middot; in {b.get("in", 0):,} B</p>'
            f'<p>uplink {escape(state)}</p>')


# ---------------------------------------------------------------- routing

def _json(body: Any, status: int = 200) -> Response:
    return status, "application/json", json.dumps(body).encode()


def _html(fragment: str) -> Response:
    return 200, "text/html; charset=utf-8", fragment.encode()


def _error(status: int, message: str) -> Response:
    return _json({"error": message}, status)


def _static(name: str) -> bytes:
    return resources.files("siab_hq").joinpath("static", name).read_bytes()


def _status_param(params: dict) -> str:
    status = params.get("status", "open")
    if status not in ("open", "resolved", "all"):
        raise BadRequest("status is open, resolved or all")
    return status


def route(app: App, method: str, target: str, body: bytes = b"") -> Response:
    url = urlsplit(target)
    path = url.path
    params = {k: v[-1] for k, v in parse_qs(url.query).items()}
    trip = params.get("trip") or app.hq.trip
    try:
        if method == "GET":
            if path in STATIC:
                name, ctype = STATIC[path]
                return 200, ctype, _static(name)
            if path == "/api/box":
                status, view = box_view(app)
                return _json(view, status)
            if path == "/panels/box":
                return _html(box_panel(app))
            if path == "/api/reconcile/status":
                return _json(app.hq.status.to_json())
            gets = {
                "/api/conservation": lambda s: _json(conservation_view(s, sql=params.get("sql") == "1")),
                "/api/tree": lambda s: _json(tree_view(s)),
                "/api/exceptions": lambda s: _json(exceptions_view(s, _status_param(params))),
                "/api/stage/units": lambda s: _json({"units": stageable(s.state, s.data.trip_doc)}),
                "/panels/conservation": lambda s: _html(conservation_panel(app, s)),
                "/panels/tree": lambda s: _html(tree_panel(s)),
                "/panels/exceptions": lambda s: _html(exceptions_panel(s, _status_param(params))),
                "/panels/stage": lambda s: _html(stage_panel(s)),
            }
            if path in gets:
                return gets[path](app.hq.snapshot(trip))
            return _error(404, "not found")
        if method == "POST":
            if path not in ("/api/exceptions/resolve", "/api/exceptions/close-superseded", "/api/stage/hq-sale",
                            "/api/reconcile/run"):
                return _error(404, "not found")
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                raise BadRequest("the body is not JSON") from None
            if not isinstance(req, dict):
                raise BadRequest("the body is a JSON object")
            trip = req.get("trip") or trip
            if path == "/api/exceptions/resolve":
                return _json(app.hq.resolve(trip, req.get("dispute_key"), req.get("transactions"),
                                            req.get("chosen_txn"), req.get("note", "")))
            if path == "/api/exceptions/close-superseded":
                return _json(app.hq.close_superseded(trip))
            if path == "/api/stage/hq-sale":
                return _json(app.hq.stage_hq_sale(trip, req.get("unit_id"), req.get("price")))
            app.hq.run_once()
            return _json(app.hq.status.to_json())
        return _error(405, "method not allowed")
    except BadRequest as e:
        return _error(400, str(e))
    except (NotFound, TripNotFound) as e:
        return _error(404, str(e))


# ---------------------------------------------------------------- the server

async def handle(app: App, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        head = await reader.readuntil(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        parts = lines[0].split(" ")
        headers = {k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in lines[1:] if h)}
        length = int(headers.get("content-length") or 0)
        if len(parts) != 3 or not 0 <= length <= MAX_BODY:
            status, ctype, body = _error(400, "bad request")
        else:
            data = await reader.readexactly(length) if length else b""
            try:
                status, ctype, body = await asyncio.to_thread(route, app, parts[0].upper(), parts[1], data)
            except Exception as e:  # noqa: BLE001 (Capella unreachable, say so rather than drop the connection)
                status, ctype, body = _error(500, f"{type(e).__name__}: {e}")
        writer.write(
            f"HTTP/1.1 {status} {REASONS.get(status, '')}\r\nContent-Type: {ctype}\r\n"
            f"Content-Length: {len(body)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n".encode() + body)
        await writer.drain()
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError, ValueError):
        pass
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def serve(app: App, port: int, host: str = "127.0.0.1") -> asyncio.Server:
    """Loopback only in Phase 0: the HQ app has no authentication."""
    return await asyncio.start_server(lambda r, w: handle(app, r, w), host, port, limit=16 * 1024)

