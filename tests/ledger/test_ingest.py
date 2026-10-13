"""Rule 0: ``ingest`` accepts what passes the schema and the cross-field rules, and drops the rest with one code."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from siab_ledger import Drop, ingest, reduce
from siab_ledger.fixtures import run
from siab_ledger.ingest import CODE_WORDS, CODES, CROSS_CHECKS, check

DOCS = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "docs"
CORPUS = sorted(DOCS.glob("*/*/*.json"))

# The code the mapping gives each invalid document of the corpus. WS10b's DocumentCheckTests lists the same.
INVALID_CODES = {
    "allocation/closed-without-closed-at": "invalid_value",
    "allocation/qty": "extra_field",
    "exception/oversell-one-transaction": "invalid_value",
    "exception/resolved-without-hlc": "missing_field",
    "exception/resolved-without-resolution": "invalid_value",
    "inventory/negative-opening": "invalid_value",
    "inventory/stored-on-hand": "extra_field",
    "product/decimal-price": "missing_field",
    "product/margin": "extra_field",
    "product/no-regions": "invalid_value",
    "transaction/check-out-to-customer": "invalid_value",
    "transaction/sale-without-tender": "invalid_value",
    "transaction/sku-not-unit-sku": "rule",
    "trip/state-name": "invalid_value",
    "trip/status-open": "invalid_value",
}


def _corpus_id(path: Path) -> str:
    return f"{path.parts[-3]}/{path.parts[-2]}/{path.stem}"


@pytest.fixture
def pack(fixture) -> dict:
    """A valid transaction: the pack of double-scan.json."""
    return copy.deepcopy(fixture("double-scan")["transactions"][0])


def test_the_corpus_lists_every_invalid_document():
    invalid = {f"{p.parts[-3]}/{p.stem}" for p in CORPUS if p.parts[-2] == "invalid"}
    assert invalid == set(INVALID_CODES)


@pytest.mark.parametrize("path", CORPUS, ids=_corpus_id)
def test_docs_corpus_agrees_with_check_contracts(path, validator):
    module, contracts = validator
    collection, kind = path.parts[-3], path.parts[-2]
    doc = json.loads(path.read_text())
    result = ingest([doc], collection)
    if kind == "valid":
        assert contracts.doc_errors(collection, doc) == []
        assert result.accepted == [doc] and result.drops == []
    else:
        assert contracts.doc_errors(collection, doc) != []
        assert result.accepted == []
        (drop,) = result.drops
        assert (drop.id, drop.collection) == (doc["_id"], collection)
        assert drop.code == INVALID_CODES[f"{collection}/{path.stem}"], drop.detail
        assert drop.detail
    # The cross-field rules are a copy of the validator's (a package may import nothing from scripts/).
    body = {k: v for k, v in doc.items() if not k.startswith("_")}
    assert set(CROSS_CHECKS) == set(module.CROSS_CHECKS)
    if collection in CROSS_CHECKS:
        assert CROSS_CHECKS[collection](body) == module.CROSS_CHECKS[collection](body)


def test_cross_checks_agree_on_crafted_failures(validator, pack, fixture):
    module, _ = validator
    exc = copy.deepcopy(fixture("double-scan")["expected"]["exceptions"]["docs"][0])
    exc.update({"status": "resolved", "resolution": {"by": "hq", "at": "2026-10-18T13:20:00Z",
                                                     "hlc": "1792329600000-0000-tablet-a", "chosen_txn": None,
                                                     "note": ""}})
    cases = [
        ("transaction", {**pack, "sku": "JKT-RAIN-L-BLU"}),
        ("transaction", {**pack, "device": "tablet-b"}),
        ("exception", {**exc, "transactions": exc["transactions"][::-1]}),
        ("exception", {**exc, "dispute_key": "SOC-WOOL-M#001|root"}),
        ("exception", exc),
        ("allocation", {"opened_at": "1792328400000-0000-tablet-a", "opened_by": "tablet-b"}),
    ]
    for collection, doc in cases:
        mine = CROSS_CHECKS[collection](doc)
        assert mine and mine == module.CROSS_CHECKS[collection](doc), (collection, mine)


def test_code_priority_and_one_drop_per_id(pack):
    pid = pack["_id"]
    missing_and_extra = {k: v for k, v in pack.items() if k != "device_clock"} | {"note": "edited"}
    assert check(missing_and_extra, "transaction")[0] == "missing_field"

    extra = {**pack, "note": "edited"}
    bad_kind = {**pack, "kind": "transfer"}
    for docs in ([extra, bad_kind], [bad_kind, extra], [bad_kind, extra, bad_kind]):
        result = ingest(docs, "transaction")
        assert result.accepted == []
        assert [(d.id, d.code) for d in result.drops] == [(pid, "extra_field")]

    # A valid body under the same id is reduced; the drop still names the id.
    result = ingest([bad_kind, pack, extra], "transaction")
    assert result.accepted == [pack]
    assert [(d.id, d.code) for d in result.drops] == [(pid, "extra_field")]

    # Keys beginning with _ are fixture metadata.
    marked = {**pack, "_why": "x", "_invalid": "y", "_anything": 1}
    assert ingest([marked], "transaction") == ([marked], [])

    # The order of the checks: malformed, wrong_type, version, then the schema, then the rules.
    assert check([pack], "transaction")[0] == "malformed"
    assert check({**pack, "type": "exception", "v": 2}, "transaction")[0] == "wrong_type"
    assert check({k: v for k, v in pack.items() if k != "type"}, "transaction")[0] == "wrong_type"
    assert check({**pack, "v": 2, "kind": "transfer"}, "transaction")[0] == "version"
    assert check({k: v for k, v in pack.items() if k != "v"}, "transaction")[0] == "version"
    assert check({**pack, "v": True}, "transaction")[0] == "version"
    assert check({**pack, "kind": "transfer", "sku": "JKT-RAIN-L-BLU"}, "transaction")[0] == "invalid_value"
    assert check({**pack, "sku": "JKT-RAIN-L-BLU"}, "transaction")[0] == "rule"


def test_drops_are_sorted_and_carry_words(pack):
    a = {**pack, "_id": "txn::b", "kind": "transfer"}
    b = {**pack, "_id": "txn::a", "v": 2}
    result = ingest([a, b], "transaction")
    assert [d.id for d in result.drops] == ["txn::a", "txn::b"]
    assert result.drops[0] == Drop("txn::a", "transaction", "version", "v: 2, not 1")
    assert result.drops[1].to_json() == {"id": "txn::b", "collection": "transaction", "code": "invalid_value",
                                         "detail": result.drops[1].detail}
    assert "transfer" in result.drops[1].detail
    assert set(CODE_WORDS) == set(CODES)
    assert CODE_WORDS["version"] == "newer schema: update the app"


@pytest.mark.parametrize("value", [None, True, 0, 1.5, "txn", [None], {}, {"_id": 5}, {"_id": "x"},
                                   {"_id": "x", "type": "transaction", "v": 1}, [[1, 2]], ("x", 3),
                                   [{"_id": "x", "type": "transaction", "v": 1, "price": float("nan")}]])
def test_ingest_never_raises_on_a_json_value(value):
    result = ingest(value, "transaction")
    assert result.accepted == []
    assert len(result.drops) == 1
    assert result.drops[0].code in ("malformed", "wrong_type", "missing_field")


def test_a_body_that_is_not_an_object_is_malformed():
    assert ingest([], "transaction") == ([], [])
    (drop,) = ingest([("txn::x", ["not", "an", "object"])], "transaction").drops
    assert (drop.id, drop.code) == ("txn::x", "malformed")
    (drop,) = ingest(["txn::x"], "transaction").drops
    assert (drop.id, drop.code) == ("", "malformed")


def test_keyerror_is_gone(pack, fixture):
    """#96 case 3: a transaction missing a required field the reducer reads made reduce raise KeyError and reduce
    nothing. Rule 0 drops it, and the rest is reduced."""
    fx = fixture("double-scan")
    broken = {k: v for k, v in fx["transactions"][1].items() if k != "prev_txn"}
    txns = [fx["transactions"][0], broken]
    with pytest.raises(KeyError):
        reduce(txns, [], store=fx["store"])
    result = ingest(txns, "transaction")
    assert [(d.id, d.code) for d in result.drops] == [(broken["_id"], "missing_field")]
    state = reduce(result.accepted, [], store=fx["store"])
    assert state.units["JKT-RAIN-M-BLU#001"].holder == "box-07"
    answer = run({**fx, "transactions": txns})
    assert answer["drops"] == [{"id": broken["_id"], "collection": "transaction", "code": "missing_field"}]


def test_contracts_dir_is_overridable_and_a_bad_one_is_a_configuration_error(monkeypatch, tmp_path, pack):
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("SIAB_CONTRACTS_DIR", str(repo / "contracts"))
    assert ingest([pack], "transaction").accepted == [pack]
    # No schemas there: that is the node's configuration, not the document's fault, so it raises rather than drop
    # every document.
    monkeypatch.setenv("SIAB_CONTRACTS_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        ingest([pack], "transaction")
    monkeypatch.delenv("SIAB_CONTRACTS_DIR")
    with pytest.raises(ValueError, match="no schema for collection"):
        ingest([pack], "transactions")
