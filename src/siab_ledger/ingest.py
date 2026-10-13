"""``ingest``: rule 0 of ``contracts/fixtures/README.md`` (decision 010). The reducer reads only what passes.

A node validates every ``transaction`` and ``exception`` it reads against its collection's schema
(``contracts/schemas/store/``) and the cross-field rules ``scripts/check_contracts.py`` checks, before ``reduce``.
A document that fails is *dropped*: not reduced, not an error, and recorded as a ``Drop`` whose ``code`` is the first
failing check in this order:

1. ``malformed``: the document is not a JSON object (or carries no string ``_id``, so nothing can name it);
2. ``wrong_type``: ``type`` is absent or not the collection's name;
3. ``version``: ``v`` is absent or not 1;
4. the schema, every error ``jsonschema`` reports mapped by its keyword (``required`` is ``missing_field``,
   ``additionalProperties`` is ``extra_field``, anything else ``invalid_value``; an ``anyOf`` or ``oneOf`` error takes
   the smallest code among its alternatives' errors), the smallest code winning;
5. ``rule``: a cross-field rule (``CROSS_CHECKS``), then the id template: the ``_id`` must be what the schema's
   ``x-id-template`` gives for the body (``expand_id``). Both are copied from ``scripts/check_contracts.py``, which a
   package may not import; ``tests/ledger/test_ingest.py`` checks the copies agree.

Keys beginning with ``_`` are fixture metadata and are ignored. One ``Drop`` per ``(collection, id)``, carrying the
smallest code among that id's invalid bodies; a valid body under the same id is still accepted. ``ingest`` never
raises on a JSON value: whatever it cannot read, it drops.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

CODES = ("malformed", "wrong_type", "version", "missing_field", "extra_field", "invalid_value", "rule")
"""The drop codes, in priority order: a document's code is the first that applies."""
RANK = {code: i for i, code in enumerate(CODES)}
CODE_WORDS = {
    "malformed": "malformed",
    "wrong_type": "wrong type",
    "version": "newer schema: update the app",
    "missing_field": "missing field",
    "extra_field": "unknown field",
    "invalid_value": "invalid value",
    "rule": "rule",
}
"""A code as both screens say it (HQ's conservation panel, the tablet's Diagnostics)."""

# Schema ids use the siab:// scheme; register it so relative references resolve (as scripts/check_contracts.py does).
if "siab" not in urllib.parse.uses_relative:
    urllib.parse.uses_relative.append("siab")
    urllib.parse.uses_netloc.append("siab")


@dataclass(frozen=True)
class Drop:
    """A document rule 0 dropped. ``detail`` is the first failing check in words: logged and shown, never compared."""

    id: str
    collection: str
    code: str
    detail: str

    def to_json(self) -> dict:
        return {"id": self.id, "collection": self.collection, "code": self.code, "detail": self.detail}

    def key(self) -> dict:
        """What a fixture's ``expected.drops`` compares: no ``detail``."""
        return {"id": self.id, "collection": self.collection, "code": self.code}


class Ingest(NamedTuple):
    accepted: list[dict]
    """The documents that pass, in input order, each with its ``_id``."""
    drops: list[Drop]
    """One per ``(collection, id)``, sorted by ``(collection, id)``."""


# ---------------------------------------------------------------- the cross-field rules (copied, not imported)

def _sku_of(unit_id: str) -> str:
    return unit_id.split("#", 1)[0]


def check_transaction(doc: dict) -> list[str]:
    errors = []
    if "unit_id" in doc and "sku" in doc and _sku_of(doc["unit_id"]) != doc["sku"]:
        errors.append(f"sku {doc['sku']} is not the SKU part of unit_id {doc['unit_id']}")
    if "hlc" in doc and "device" in doc and not str(doc["hlc"]).endswith("-" + str(doc["device"])):
        errors.append(f"hlc {doc['hlc']} does not end with the device id {doc['device']}")
    return errors


def check_allocation(doc: dict) -> list[str]:
    if "opened_at" in doc and "opened_by" in doc and not str(doc["opened_at"]).endswith("-" + str(doc["opened_by"])):
        return [f"opened_at {doc['opened_at']} does not end with opened_by {doc['opened_by']}"]
    return []


def check_exception(doc: dict) -> list[str]:
    errors = []
    txns, branches = doc.get("transactions"), doc.get("branches")
    if isinstance(txns, list):
        if txns != sorted(txns):
            errors.append("transactions are not sorted")
        if isinstance(branches, list) and [b.get("txn") for b in branches if isinstance(b, dict)] != txns:
            errors.append("branches[i].txn does not match transactions[i]")
    if "unit_id" in doc and "sku" in doc and _sku_of(doc["unit_id"]) != doc["sku"]:
        errors.append(f"sku {doc['sku']} is not the SKU part of unit_id {doc['unit_id']}")
    if "unit_id" in doc and "dispute_key" in doc and not str(doc["dispute_key"]).startswith(doc["unit_id"] + "|"):
        errors.append(f"dispute_key {doc['dispute_key']} does not start with the unit_id")
    res = doc.get("resolution")
    if isinstance(res, dict) and "hlc" in res and "by" in res and not str(res["hlc"]).endswith("-" + str(res["by"])):
        errors.append(f"resolution.hlc {res['hlc']} does not end with resolution.by {res['by']}")
    return errors


CROSS_CHECKS = {"transaction": check_transaction, "allocation": check_allocation, "exception": check_exception}


def sha256_8(ids: list[str]) -> str:
    """The exception id hash: first 8 hex chars of sha256 over the ids, sorted and joined by '|'."""
    return hashlib.sha256("|".join(sorted(ids)).encode()).hexdigest()[:8]


def expand_id(template: str, doc: dict) -> str | None:
    """Fill an x-id-template ({field} or {sha256_8:field}) from a document; None if a field is missing."""
    out = template
    for token in re.findall(r"\{([^}]+)\}", template):
        func, _, field = token.rpartition(":")
        if field not in doc:
            return None
        value = sha256_8(doc[field]) if func == "sha256_8" else doc[field]
        out = out.replace("{" + token + "}", str(value))
    return out


# ---------------------------------------------------------------- the schemas

def _format_checker() -> FormatChecker:
    """``date`` and ``date-time`` checked as ``scripts/check_contracts.py`` checks them."""
    checker = FormatChecker(formats=())

    @checker.checks("date", raises=ValueError)
    def is_date(value) -> bool:
        if not isinstance(value, str):
            return True
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("not YYYY-MM-DD")
        date.fromisoformat(value)
        return True

    @checker.checks("date-time", raises=ValueError)
    def is_date_time(value) -> bool:
        if not isinstance(value, str):
            return True
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})", value):
            raise ValueError("not RFC 3339")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True

    return checker


def default_contracts_dir() -> Path:
    """``SIAB_CONTRACTS_DIR`` when set, else ``contracts/`` of the repository the working directory (else this
    package) is in, found as the fixture runner finds its fixtures."""
    if env := os.environ.get("SIAB_CONTRACTS_DIR"):
        return Path(env)
    for start in (Path.cwd().resolve(), Path(__file__).resolve()):
        for parent in (start, *start.parents):
            candidate = parent / "contracts"
            if (candidate / "schemas" / "store").is_dir():
                return candidate
    raise FileNotFoundError("contracts/schemas not found; set SIAB_CONTRACTS_DIR")


def validators(contracts_dir: Path | None = None) -> dict[str, Draft202012Validator]:
    """One validator per collection under ``<contracts_dir>/schemas/store/`` (default: ``default_contracts_dir()``),
    references resolved. A missing or empty schema directory is a configuration error and raises."""
    return _validators(Path(contracts_dir) if contracts_dir is not None else default_contracts_dir())


@cache
def _validators(contracts_dir: Path) -> dict[str, Draft202012Validator]:
    schemas = {}
    for path in sorted((Path(contracts_dir) / "schemas").rglob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[schema["$id"]] = schema
    registry = Registry().with_resources(
        (sid, Resource.from_contents(schema, default_specification=DRAFT202012)) for sid, schema in schemas.items())
    checker = _format_checker()
    prefix = "siab://contracts/store/"
    out = {sid.removeprefix(prefix).removesuffix(".schema.json"):
           Draft202012Validator(schema, registry=registry, format_checker=checker)
           for sid, schema in schemas.items() if sid.startswith(prefix)}
    if not out:
        raise FileNotFoundError(f"no collection schemas under {contracts_dir / 'schemas' / 'store'}")
    return out


# ---------------------------------------------------------------- one document

_JSON_TYPES = ((dict, "an object"), (list, "an array"), (str, "a string"), (bool, "a boolean"),
               ((int, float), "a number"), (type(None), "null"))


def _json_type(value: Any) -> str:
    return next((name for kind, name in _JSON_TYPES if isinstance(value, kind)), type(value).__name__)


def _where(path: Iterable) -> str:
    return ".".join(str(p) for p in path)


def _error_code(error) -> str:
    if error.validator in ("anyOf", "oneOf") and error.context:
        return min((_error_code(e) for e in error.context), key=RANK.__getitem__)
    if error.validator == "required":
        return "missing_field"
    if error.validator == "additionalProperties":
        return "extra_field"
    return "invalid_value"


def _leaf(error):
    """The error whose words explain ``_error_code(error)``: for ``anyOf``, the alternative's error with that code."""
    if error.validator in ("anyOf", "oneOf") and error.context:
        code = _error_code(error)
        # The alternative the value was meant for: not a bare type mismatch, the deepest error first.
        return _leaf(min((e for e in error.context if _error_code(e) == code),
                         key=lambda e: (e.validator == "type", -len(e.absolute_path), _where(e.absolute_path),
                                        e.message)))
    return error


def _words(error) -> str:
    where = _where(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = [k for k in error.validator_value if k not in error.instance]
        if missing:
            return f"{_where([*error.absolute_path, missing[0]])}: required"
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        known = set(error.schema.get("properties", {}))
        extra = sorted(k for k in error.instance if k not in known)
        if extra:
            return f"{_where([*error.absolute_path, extra[0]])}: unknown field"
    return f"{where or '(root)'}: {error.message}"


def check(doc: Any, collection: str, contracts_dir: Path | None = None) -> tuple[str, str] | None:
    """``(code, detail)`` when ``doc`` (one document, ``_``-keys ignored) fails rule 0, else None. A collection with
    no schema is the caller's error (``ValueError``), not the document's."""
    validator = validators(contracts_dir).get(collection)
    if validator is None:
        raise ValueError(f"no schema for collection {collection!r}")
    if not isinstance(doc, dict):
        return "malformed", f"the document is {_json_type(doc)}, not an object"
    body = {k: v for k, v in doc.items() if not (isinstance(k, str) and k.startswith("_"))}
    if body.get("type") != collection:
        return "wrong_type", f"type: {json.dumps(body['type']) if 'type' in body else 'required'}, not {collection}"
    v = body.get("v")
    if "v" not in body or isinstance(v, bool) or not isinstance(v, int | float) or v != 1:
        return "version", f"v: {json.dumps(v) if 'v' in body else 'required'}, not 1"
    errors = list(validator.iter_errors(body))
    if errors:
        code = min((_error_code(e) for e in errors), key=RANK.__getitem__)
        first = min((_leaf(e) for e in errors if _error_code(e) == code),
                    key=lambda e: (_where(e.absolute_path), e.message))
        return code, _words(first)
    rule = CROSS_CHECKS.get(collection, lambda _: [])(body)
    if rule:
        return "rule", rule[0]
    template = validator.schema.get("x-id-template")
    if template is not None:  # the id is what the body says it is, or exceptions_for would name an invalid id
        want = expand_id(template, body)
        if "_id" not in doc:
            return "rule", "_id: required"
        if want is not None and doc["_id"] != want:
            return "rule", f"_id {doc['_id']} should be {want}"
    return None


# ---------------------------------------------------------------- many documents

def _id_and_doc(item: Any) -> tuple[str | None, Any]:
    """A document with its ``_id``, or an ``(id, body)`` pair (a tuple, which JSON never produces)."""
    if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
        doc = item[1]
        return item[0], ({**doc, "_id": item[0]} if isinstance(doc, dict) else doc)
    if isinstance(item, dict) and isinstance(item.get("_id"), str):
        return item["_id"], item
    return None, item


def ingest(docs: Any, collection: str, *, contracts_dir: Path | None = None) -> Ingest:
    """Rule 0 over ``docs`` (raw documents with ``_id``, any order, duplicates allowed) of one ``collection``.

    ``accepted`` are the documents that pass, in input order; ``drops`` one per id, the smallest code among that id's
    invalid bodies (ties broken by ``detail``, so the record is a function of the set). Never raises on JSON input:
    ``docs`` that is not a list is read as one document. A missing schema directory or an unknown ``collection`` is
    a configuration error and raises before any document is read."""
    if collection not in validators(contracts_dir):
        raise ValueError(f"no schema for collection {collection!r}")
    if isinstance(docs, str | bytes | Mapping) or not isinstance(docs, Iterable):
        docs = [docs]
    accepted: list[dict] = []
    worst: dict[str, tuple[int, str]] = {}
    for item in docs:
        doc_id, doc = _id_and_doc(item)
        if doc_id is None:
            failed = ("malformed", f"the document is {_json_type(doc)} with no string _id")
            doc_id = ""
        else:
            try:
                failed = check(doc, collection, contracts_dir)
            except Exception as e:  # noqa: BLE001 (rule 0: what cannot be read is dropped, never raised)
                failed = ("malformed", f"the validator could not read it: {type(e).__name__}: {e}")
        if failed is None:
            accepted.append(doc)
            continue
        rank = (RANK[failed[0]], failed[1])
        if doc_id not in worst or rank < worst[doc_id]:
            worst[doc_id] = rank
    drops = [Drop(doc_id, collection, CODES[rank], detail) for doc_id, (rank, detail) in sorted(worst.items())]
    return Ingest(accepted, drops)
