"""exceptions_for: deterministic ids, byte-identical output, and documents that validate against the contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from siab_ledger import exception_id, exceptions_for, reduce

LEDGER_FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "ledger"
FIXTURE_NAMES = [p.stem for p in sorted(LEDGER_FIXTURES.glob("*.json"))]
DETECTED_AT = "1792340000000-0000-tablet-a"


def test_exception_id_is_deterministic(fixture):
    ids = ["txn::1792328511000-0000-tablet-b", "txn::1792328510000-0000-tablet-a"]
    assert exception_id("tablet-a", "JKT-RAIN-M-BLU#001", ids) == "exc::tablet-a::JKT-RAIN-M-BLU#001::111c7a4e"
    assert exception_id("tablet-a", "JKT-RAIN-M-BLU#001", ids[::-1]) == "exc::tablet-a::JKT-RAIN-M-BLU#001::111c7a4e"
    assert exception_id("tablet-b", "JKT-RAIN-M-BLU#001", ids) == "exc::tablet-b::JKT-RAIN-M-BLU#001::111c7a4e"

    fx = fixture("double-scan")
    first = exceptions_for(reduce(fx["transactions"], [], store=fx["store"]), "tablet-a", fx["trip"], fx["box"])
    again = exceptions_for(reduce(fx["transactions"][::-1], [], store=fx["store"]), "tablet-a", fx["trip"], fx["box"])
    assert json.dumps(first) == json.dumps(again)

    # A new branch at the same fork is a new document (rule 7), never an update of the old one.
    third = dict(fx["transactions"][2], _id="txn::1792328512000-0000-phone-1", device="phone-1",
                 hlc="1792328512000-0000-phone-1", to_custodian="phone-1")
    grown = exceptions_for(reduce(fx["transactions"] + [third], [], store=fx["store"]), "tablet-a", fx["trip"],
                           fx["box"])
    assert len(grown) == 1
    assert grown[0]["_id"] != first[0]["_id"]
    assert grown[0]["dispute_key"] == first[0]["dispute_key"]
    assert grown[0]["transactions"] == sorted([*first[0]["transactions"], third["_id"]])


@pytest.mark.parametrize("name", FIXTURE_NAMES)
@pytest.mark.parametrize("detector", ["tablet-a", "hq"])
def test_exception_documents_validate(name, detector, fixture, validator):
    module, contracts = validator
    fx = fixture(name)
    state = reduce(fx["transactions"], fx["resolutions"], store=fx["store"])
    docs = exceptions_for(state, detector, fx["trip"], fx["box"], detected_at=f"1792340000000-0000-{detector}")
    for doc in docs:
        assert contracts.doc_errors("exception", doc) == [], doc["_id"]
        assert doc["box"] == (None if detector == "hq" else fx["box"])
        assert doc["detected_by"] == detector


def test_unresolved_unit_with_resolutions_still_validates(fixture, validator):
    """Exceptions emitted next to an unrelated resolution validate too."""
    _, contracts = validator
    fx = fixture("non-hq-resolution-ignored")
    state = reduce(fx["transactions"], fx["resolutions"], store=fx["store"])
    (doc,) = exceptions_for(state, "tablet-a", fx["trip"], fx["box"], detected_at=DETECTED_AT)
    assert contracts.doc_errors("exception", doc) == []


def test_detected_at_only_when_given(fixture):
    fx = fixture("double-scan")
    state = reduce(fx["transactions"], [], store=fx["store"])
    (plain,) = exceptions_for(state, "tablet-a", fx["trip"], fx["box"])
    (stamped,) = exceptions_for(state, "tablet-a", fx["trip"], fx["box"], detected_at=DETECTED_AT)
    assert "detected_at" not in plain
    assert stamped == {**plain, "detected_at": DETECTED_AT}


def test_kinds_and_fixed_notes(fixture):
    fx = fixture("oversell-hq")
    (doc,) = exceptions_for(reduce(fx["transactions"], [], store=fx["store"]), "tablet-a", fx["trip"], fx["box"])
    assert (doc["kind"], doc["dispute_key"], doc["fork_txn"]) == ("oversell", "JKT-RAIN-M-BLU#001|root", None)
    assert doc["proposed_resolution"] == {
        "action": "refund", "note": "Sold twice. Refund one sale, then choose the branch that stands."}

    fx = fixture("unexpected-check-in")
    (doc,) = exceptions_for(reduce(fx["transactions"], [], store=fx["store"]), "tablet-a", fx["trip"], fx["box"])
    assert doc["kind"] == "unexpected_check_in"
    assert doc["proposed_resolution"]["note"] == (
        "Checked in by a device that did not hold it. Confirm where the unit is.")


def test_unexpected_check_in_attaches_its_predecessor_only_when_present(fixture):
    fx = fixture("unexpected-check-in")
    check_in = fx["transactions"][2]
    alone = exceptions_for(reduce([check_in], [], store=fx["store"]), "tablet-a", fx["trip"], fx["box"])
    assert [d["transactions"] for d in alone] == [[check_in["_id"]]]


def test_a_check_in_from_the_box_or_its_writer_is_expected(fixture):
    fx = fixture("conservation-day")  # tablet-a checks a shell in from the box to the store at close
    state = reduce(fx["transactions"], [], store=fx["store"])
    kinds = [d["kind"] for d in exceptions_for(state, "tablet-a", fx["trip"], fx["box"])]
    assert kinds == ["double_scan"]


def test_resolved_exception_is_left_out_but_others_stay(fixture):
    fx = fixture("resolved-fork")
    extra = copy.deepcopy(fixture("unexpected-check-in")["transactions"][2])
    extra.update(prev_txn="txn::1792328510000-0000-tablet-a")
    state = reduce(fx["transactions"] + [extra], fx["resolutions"], store=fx["store"])
    assert [d["kind"] for d in exceptions_for(state, "tablet-a", fx["trip"], fx["box"])] == ["unexpected_check_in"]
