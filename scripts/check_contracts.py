"""Check that every contract fixture agrees with its schema, so a fixture can never drift from the contract.

Usage: python3 scripts/check_contracts.py [--contracts DIR] [-v]     (from the repository root)
       python3 scripts/check_contracts.py --self-test

Checks (one line per problem, exit 1 on any):
1. every fixtures/docs/<collection>/valid/*.json validates against schemas/store/<collection>.schema.json and its id
   matches the schema's x-id-template; every invalid/*.json fails (and says why in "_why");
2. every seed document in fixtures/seed/*.json validates against its collection's schema; custodians.json against
   schemas/fixtures/custodians.schema.json;
3. every fixtures/ledger/*.json matches schemas/fixtures/ledger.schema.json, and its inventory[], transactions[],
   resolutions[] and expected.exceptions.docs[] validate against their collection schemas, ids included;
4. every fixtures/sync/*.json matches schemas/fixtures/sync-case.schema.json, and its doc and non-null oldDoc validate
   against the case's collection schema (a delete, and a doc marked "invalid_doc", are the exceptions: an invalid_doc
   must fail);
5. VERSION is semver and is the first version line in CHANGELOG.md.
Besides the JSON Schema, a few cross-field rules the schemas cannot express are checked (CROSS_CHECKS below).
Needs only the standard library and jsonschema (>= 4.18), so it runs before the project's own environment exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from datetime import date, datetime
from pathlib import Path

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
except ImportError:  # pragma: no cover
    sys.exit("check_contracts: needs jsonschema >= 4.18 (pip install 'jsonschema>=4.18')")

STRIPPED = ("_id", "_why")  # fixture metadata, removed before a document is validated
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CHANGELOG_VERSION = re.compile(r"^\s*[-*]?\s*\**\s*(\d+\.\d+\.\d+)")
SEED_COLLECTIONS = {"products.json": "product", "inventory.json": "inventory", "trips.json": "trip"}
# Schema ids use the siab:// scheme. RFC 3986 resolves "../common.schema.json" against it, but Python's urljoin only
# does so for schemes it knows, so register this one.
urllib.parse.uses_relative.append("siab")
urllib.parse.uses_netloc.append("siab")
# A placeholder for detected_at, which ledger fixtures leave out of expected exceptions (it is the detector's clock).
DETECTED_AT_PLACEHOLDER = "0000000000000-0000-placeholder"


# ---------------------------------------------------------------- pure helpers (covered by --self-test)

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


def sku_of(unit_id: str) -> str:
    return unit_id.split("#", 1)[0]


def check_transaction(doc: dict) -> list[str]:
    errors = []
    if "unit_id" in doc and "sku" in doc and sku_of(doc["unit_id"]) != doc["sku"]:
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
    if "unit_id" in doc and "sku" in doc and sku_of(doc["unit_id"]) != doc["sku"]:
        errors.append(f"sku {doc['sku']} is not the SKU part of unit_id {doc['unit_id']}")
    if "unit_id" in doc and "dispute_key" in doc and not str(doc["dispute_key"]).startswith(doc["unit_id"] + "|"):
        errors.append(f"dispute_key {doc['dispute_key']} does not start with the unit_id")
    return errors


CROSS_CHECKS = {"transaction": check_transaction, "allocation": check_allocation, "exception": check_exception}


def format_checker() -> FormatChecker:
    """date and date-time checked with the standard library, so no extra format packages are needed."""
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


class Contracts:
    """The schemas under one contracts/ directory, ready to validate documents by collection."""

    def __init__(self, schemas: dict[str, dict]):
        # schemas: $id -> schema
        registry = Registry().with_resources(
            (sid, Resource.from_contents(schema, default_specification=DRAFT202012)) for sid, schema in schemas.items())
        checker = format_checker()
        self.by_id = schemas
        self.validators = {
            sid: Draft202012Validator(schema, registry=registry, format_checker=checker)
            for sid, schema in schemas.items()}

    @classmethod
    def load(cls, root: Path) -> "Contracts":
        schemas = {}
        for path in sorted((root / "schemas").rglob("*.schema.json")):
            schema = json.loads(path.read_text())
            schemas[schema["$id"]] = schema
        return cls(schemas)

    def schema_errors(self, sid: str, instance) -> list[str]:
        errors = sorted(self.validators[sid].iter_errors(instance), key=lambda e: list(e.absolute_path))
        return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in errors]

    def doc_errors(self, collection: str, doc: dict) -> list[str]:
        """Schema errors, cross-field errors and id errors for one fixture document (with its _id)."""
        sid = f"siab://contracts/store/{collection}.schema.json"
        if sid not in self.validators:
            return [f"no schema for collection {collection}"]
        body = {k: v for k, v in doc.items() if k not in STRIPPED}
        errors = self.schema_errors(sid, body)
        errors += CROSS_CHECKS.get(collection, lambda _: [])(body)
        template = self.by_id[sid].get("x-id-template")
        if template is not None:
            want = expand_id(template, body)
            if "_id" not in doc:
                errors.append("missing _id")
            elif want is not None and doc["_id"] != want:
                errors.append(f"_id {doc['_id']} should be {want}")
        return errors


# ---------------------------------------------------------------- the checks

def load_json(path: Path, problems: list[str]):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        problems.append(f"{path}: not readable JSON: {e}")
        return None


def check_docs(root: Path, c: Contracts, problems: list[str], verbose: bool) -> int:
    n = 0
    for coll_dir in sorted((root / "fixtures" / "docs").glob("*/")):
        collection = coll_dir.name
        for path in sorted((coll_dir / "valid").glob("*.json")):
            n += 1
            doc = load_json(path, problems)
            if doc is not None:
                problems += [f"{path}: {e}" for e in c.doc_errors(collection, doc)]
        for path in sorted((coll_dir / "invalid").glob("*.json")):
            n += 1
            doc = load_json(path, problems)
            if doc is None:
                continue
            if not doc.get("_why"):
                problems.append(f"{path}: an invalid fixture must say why in _why")
            errors = c.doc_errors(collection, doc)
            if not errors:
                problems.append(f"{path}: should fail validation ({doc.get('_why')}) but passes")
            elif verbose:
                print(f"  invalid as expected: {path.name}: {errors[0]}")
    return n


def check_seed(root: Path, c: Contracts, problems: list[str]) -> int:
    n = 0
    seed_dir = root / "fixtures" / "seed"
    for path in sorted(seed_dir.glob("*.json")):
        data = load_json(path, problems)
        if data is None:
            continue
        if path.name == "custodians.json":
            n += 1
            problems += [f"{path}: {e}" for e in
                         c.schema_errors("siab://contracts/fixtures/custodians.schema.json", data)]
            continue
        collection = SEED_COLLECTIONS.get(path.name)
        if collection is None:
            problems.append(f"{path}: unknown seed file (expected one of {sorted(SEED_COLLECTIONS)} or custodians.json)")
            continue
        if not isinstance(data, list):
            problems.append(f"{path}: a seed file is an array of documents")
            continue
        ids = [d.get("_id") for d in data if isinstance(d, dict)]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            problems.append(f"{path}: duplicate _id {dup}")
        for i, doc in enumerate(data):
            n += 1
            problems += [f"{path}[{i}]: {e}" for e in c.doc_errors(collection, doc)]
    return n


def check_ledger(root: Path, c: Contracts, problems: list[str]) -> int:
    n = 0
    for path in sorted((root / "fixtures" / "ledger").glob("*.json")):
        n += 1
        fx = load_json(path, problems)
        if fx is None:
            continue
        errors = c.schema_errors("siab://contracts/fixtures/ledger.schema.json", fx)
        problems += [f"{path}: {e}" for e in errors]
        if errors:
            continue
        if fx["name"] != path.stem:
            problems.append(f"{path}: name {fx['name']} does not match the file name")
        groups = [("inventory", "inventory", fx["inventory"] or []),
                  ("transactions", "transaction", fx["transactions"]),
                  ("resolutions", "exception", fx["resolutions"])]
        expected_docs = [{**d, "detected_at": DETECTED_AT_PLACEHOLDER} for d in fx["expected"]["exceptions"]["docs"]]
        groups.append(("expected.exceptions.docs", "exception", expected_docs))
        for label, collection, docs in groups:
            for i, doc in enumerate(docs):
                problems += [f"{path}: {label}[{i}] {doc.get('_id')}: {e}" for e in c.doc_errors(collection, doc)]
        for doc in fx["transactions"]:
            if doc.get("trip") != fx["trip"]:
                problems.append(f"{path}: {doc['_id']} is on trip {doc.get('trip')}, not {fx['trip']}")
        for doc in fx["resolutions"]:
            if doc.get("status") != "resolved":
                problems.append(f"{path}: resolution {doc['_id']} is not resolved")
        for doc in fx["expected"]["exceptions"]["docs"]:
            if doc.get("detected_by") != fx["expected"]["exceptions"]["detector"]:
                problems.append(f"{path}: expected exception {doc['_id']} is not from the detector")
        ids = [d["_id"] for d in fx["transactions"]]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            problems.append(f"{path}: duplicate transaction {dup}")
    return n


def check_sync(root: Path, c: Contracts, problems: list[str], verbose: bool) -> int:
    n = 0
    for path in sorted((root / "fixtures" / "sync").glob("*.json")):
        n += 1
        case = load_json(path, problems)
        if case is None:
            continue
        errors = c.schema_errors("siab://contracts/fixtures/sync-case.schema.json", case)
        problems += [f"{path}: {e}" for e in errors]
        if errors:
            continue
        if case["name"] != path.stem:
            problems.append(f"{path}: name {case['name']} does not match the file name")
        collection, doc = case["collection"], case["doc"]
        if doc.get("_deleted") is True:
            if set(doc) != {"_id", "_deleted"}:
                problems.append(f"{path}: a delete is doc {{_id, _deleted: true}} and nothing else")
        else:
            doc_errors = c.doc_errors(collection, doc)
            if "invalid_doc" in case:
                if not doc_errors:
                    problems.append(f"{path}: doc is marked invalid_doc ({case['invalid_doc']}) but validates")
                elif verbose:
                    print(f"  invalid doc as expected: {path.name}: {doc_errors[0]}")
            else:
                problems += [f"{path}: doc: {e}" for e in doc_errors]
        if case["oldDoc"] is not None:
            problems += [f"{path}: oldDoc: {e}" for e in c.doc_errors(collection, case["oldDoc"])]
            if case["oldDoc"]["_id"] != doc["_id"]:
                problems.append(f"{path}: doc and oldDoc have different _id")
    return n


def check_version(root: Path, problems: list[str]) -> str | None:
    try:
        version = (root / "VERSION").read_text().strip()
        changelog = (root / "CHANGELOG.md").read_text()
    except OSError as e:
        problems.append(f"{root}: {e}")
        return None
    if not SEMVER.match(version):
        problems.append(f"{root / 'VERSION'}: {version!r} is not semver")
    first = next((m.group(1) for line in changelog.splitlines() if (m := CHANGELOG_VERSION.match(line))), None)
    if first != version:
        problems.append(f"{root / 'CHANGELOG.md'}: first version line is {first}, VERSION is {version}")
    return version


def run(root: Path, verbose: bool = False) -> list[str]:
    problems: list[str] = []
    version = check_version(root, problems)
    c = Contracts.load(root)
    counts = {
        "docs": check_docs(root, c, problems, verbose),
        "seed": check_seed(root, c, problems),
        "ledger": check_ledger(root, c, problems),
        "sync": check_sync(root, c, problems, verbose),
    }
    summary = ", ".join(f"{k} {v}" for k, v in counts.items())
    print(f"contracts {version}: {len(c.by_id)} schemas; checked {summary}")
    return problems


# ---------------------------------------------------------------- self-test

def self_test() -> None:
    common = {
        "$id": "siab://contracts/common.schema.json",
        "$defs": {"sku": {"type": "string", "pattern": "^[A-Z]+$"}},
    }
    thing = {
        "$id": "siab://contracts/store/thing.schema.json",
        "x-id-template": "thing::{sku}",
        "type": "object",
        "additionalProperties": False,
        "required": ["sku", "when"],
        "properties": {"sku": {"$ref": "../common.schema.json#/$defs/sku"}, "when": {"format": "date-time"}},
    }
    c = Contracts({s["$id"]: s for s in (common, thing)})
    good = {"_id": "thing::ABC", "sku": "ABC", "when": "2026-10-18T13:00:00Z"}
    assert c.doc_errors("thing", good) == [], c.doc_errors("thing", good)
    assert c.doc_errors("thing", {**good, "_id": "thing::XYZ"}), "id template not checked"
    assert c.doc_errors("thing", {**good, "sku": "abc", "_id": "thing::abc"}), "$ref not followed"
    assert c.doc_errors("thing", {**good, "when": "18 Oct 2026"}), "date-time not checked"
    assert c.doc_errors("thing", {**good, "margin": 1}), "additionalProperties not enforced"
    assert c.doc_errors("nothing", good) == ["no schema for collection nothing"]
    assert sha256_8(["b", "a"]) == hashlib.sha256(b"a|b").hexdigest()[:8]
    assert expand_id("exc::{d}::{sha256_8:t}", {"d": "x", "t": ["b", "a"]}) == "exc::x::" + sha256_8(["a", "b"])
    assert check_transaction({"unit_id": "A-B#001", "sku": "A-B", "hlc": "1-0000-tablet-a", "device": "tablet-a"}) == []
    assert len(check_transaction({"unit_id": "A-B#001", "sku": "A", "hlc": "1-0000-tablet-a", "device": "hq"})) == 2
    assert check_exception({"transactions": ["b", "a"], "branches": [{"txn": "b"}, {"txn": "a"}]}) == [
        "transactions are not sorted"]
    assert CHANGELOG_VERSION.match("- 0.1.0 (2026-10-07): first").group(1) == "0.1.0"
    print("self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check contract fixtures against their schemas.")
    parser.add_argument("--contracts", type=Path, default=Path("contracts"))
    parser.add_argument("-v", "--verbose", action="store_true", help="also show why each invalid fixture fails")
    parser.add_argument("--self-test", action="store_true", help="check the helpers on in-memory examples and exit")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    problems = run(args.contracts, args.verbose)
    for p in problems:
        print(p)
    print(f"{len(problems)} problem(s)" if problems else "all contract fixtures agree with their schemas")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
