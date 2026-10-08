"""reduce: chains, forks, blind movements and resolutions (rules 1 to 5)."""

from __future__ import annotations

import copy

from siab_ledger import exceptions_for, reduce

STORE = "store-richmond"
PACK_1 = "txn::1792328410000-0000-tablet-a"
TAKE_A = "txn::1792328510000-0000-tablet-a"
TAKE_B = "txn::1792328511000-0000-tablet-b"


def state_of(fx, transactions=None, resolutions=None):
    return reduce(fx["transactions"] if transactions is None else transactions,
                  fx["resolutions"] if resolutions is None else resolutions, store=fx["store"])


def chain_to(state, txn_id, limit=50):
    """The predecessor chain ending at txn_id, oldest first; fails (never hangs) on a cycle."""
    chain = [txn_id]
    while (prev := state.predecessors.get(chain[-1])) is not None and prev in state.transactions:
        assert prev not in chain, f"cycle through {prev}"
        assert len(chain) < limit
        chain.append(prev)
    return chain[::-1]


def test_linear_chain_pack_and_sell(fixture):
    state = state_of(fixture("pack-and-sell"))
    assert state.forks == ()
    assert state.units["JKT-RAIN-M-BLU#002"].state == "sold"
    assert state.counts == {("box-07", "JKT-RAIN-M-BLU"): 2}


def test_dangling_predecessor_is_not_a_fork(fixture):
    fx = fixture("dangling-predecessor")
    state = state_of(fx)
    assert state.forks == ()
    (check_in,) = fx["transactions"]
    assert check_in["prev_txn"] not in state.transactions
    unit = state.units["JKT-RAIN-M-BLU#001"]
    assert (unit.holder, unit.state, unit.last_txn) == ("box-07", "held", check_in["_id"])
    assert exceptions_for(state, "tablet-a", fx["trip"], fx["box"]) == []


def test_dangling_roots_naming_one_predecessor_fork(fixture):
    dangling = state_of(fixture("dangling-double-take"))
    (fork,) = dangling.forks
    assert fork.prev_txn == PACK_1
    assert PACK_1 not in dangling.transactions
    assert fork.branches == (TAKE_A, TAKE_B)
    assert dangling.units["JKT-RAIN-M-BLU#001"].state == "disputed"
    fx = fixture("double-scan")
    docs = exceptions_for(dangling, "tablet-a", fx["trip"], fx["box"])
    assert [d["_id"] for d in docs] == ["exc::tablet-a::JKT-RAIN-M-BLU#001::111c7a4e"]
    # The pack's arrival changes nothing: the same document double-scan gives.
    assert docs == exceptions_for(state_of(fx), "tablet-a", fx["trip"], fx["box"])
    # And a single dangling root is still no fork.
    assert state_of(fixture("dangling-predecessor")).forks == ()


def test_resolution_settles_fork(fixture):
    fx = fixture("resolved-fork")
    unresolved = state_of(fx, resolutions=[])
    assert unresolved.units["JKT-RAIN-M-BLU#001"].state == "disputed"
    assert len(exceptions_for(unresolved, "tablet-a", fx["trip"], fx["box"])) == 1

    state = state_of(fx)
    (fork,) = state.forks
    assert fork.resolved_by == fx["resolutions"][0]["_id"]
    unit = state.units["JKT-RAIN-M-BLU#001"]
    assert (unit.holder, unit.state, unit.last_txn) == ("tablet-a", "held", TAKE_A)
    assert state.counts == {("tablet-a", "JKT-RAIN-M-BLU"): 1}
    assert state.allocation_counts["alloc::1792328501000-0000-tablet-b"] == 0
    assert exceptions_for(state, "tablet-a", fx["trip"], fx["box"]) == []

    # Choosing the other branch makes it canonical instead.
    other = copy.deepcopy(fx["resolutions"])
    other[0]["resolution"]["chosen_txn"] = TAKE_B
    flipped = state_of(fx, resolutions=other).units["JKT-RAIN-M-BLU#001"]
    assert (flipped.holder, flipped.last_txn) == ("tablet-b", TAKE_B)


def test_non_hq_resolution_is_ignored(fixture):
    fx = fixture("non-hq-resolution-ignored")
    state = state_of(fx)
    assert state.resolutions == ()
    assert state.forks[0].resolved_by is None
    assert state.units["JKT-RAIN-M-BLU#001"].state == "disputed"
    assert len(exceptions_for(state, "tablet-a", fx["trip"], fx["box"])) == 1


def test_open_exception_is_not_a_resolution(fixture):
    fx = fixture("resolved-fork")
    still_open = copy.deepcopy(fx["resolutions"])
    still_open[0].update(status="open")
    assert state_of(fx, resolutions=still_open).units["JKT-RAIN-M-BLU#001"].state == "disputed"


def test_resolution_without_a_chosen_branch_leaves_the_unit_disputed_but_writes_nothing_new(fixture):
    fx = fixture("resolved-fork")
    dismissed = copy.deepcopy(fx["resolutions"])
    dismissed[0]["resolution"]["chosen_txn"] = None
    state = state_of(fx, resolutions=dismissed)
    assert state.forks[0].resolved_by is None
    assert state.units["JKT-RAIN-M-BLU#001"].state == "disputed"
    assert exceptions_for(state, "tablet-a", fx["trip"], fx["box"]) == []  # rule 7: it matches the resolution


def test_blind_take_links_under_the_pack(fixture):
    # Pack arrives after the blind take: the take is the pack's child, no fork, tablet-b holds.
    state = state_of(fixture("null-root-take-pack-arrives"))
    assert state.forks == ()
    unit = state.units["JKT-RAIN-M-BLU#005"]
    assert (unit.holder, unit.state) == ("tablet-b", "held")
    assert chain_to(state, "txn::1792329400000-0000-tablet-b") == [
        "txn::1792328450000-0000-tablet-a", "txn::1792329400000-0000-tablet-b"]

    # A genuine double take with one blind side forks at the pack, not at the root.
    (fork,) = state_of(fixture("null-root-double-take")).forks
    assert fork.prev_txn == "txn::1792328450000-0000-tablet-a"
    assert fork.branches == ("txn::1792328550000-0000-tablet-a", "txn::1792329400000-0000-tablet-b")

    # A later return to the box does not capture the blind take: no cycle, one chain.
    state = state_of(fixture("null-root-take-returned"))
    assert state.forks == ()
    assert chain_to(state, state.units["JKT-RAIN-M-BLU#005"].last_txn) == [
        "txn::1792328450000-0000-tablet-a",  # pack
        "txn::1792329400000-0000-tablet-b",  # blind take
        "txn::1792331450000-0000-tablet-b",  # return
        "txn::1792332000000-0000-tablet-a",  # take
    ]
    assert state.units["JKT-RAIN-M-BLU#005"].holder == "tablet-a"

    # The blind take continues the latest movement into the box below it (the return), not the earliest (the pack).
    state = state_of(fixture("null-root-take-after-return"))
    assert state.forks == ()
    assert state.predecessors["txn::1792329400000-0000-tablet-b"] == "txn::1792328650000-0000-tablet-a"
    assert state.units["JKT-RAIN-M-BLU#005"].holder == "tablet-b"

    # A blind sale is blind too: it forks with the take at the pack, and the later branch being a sale, an oversell.
    fx = fixture("null-root-sale-oversell")
    state = state_of(fx)
    (fork,) = state.forks
    assert fork.prev_txn == "txn::1792328450000-0000-tablet-a"
    assert [d["kind"] for d in exceptions_for(state, "tablet-a", fx["trip"], fx["box"])] == ["oversell"]

    # A set-aside branch still counts as the implied predecessor: the blind take descends from it and is ignored.
    fx = fixture("null-root-take-resolved-fork")
    state = state_of(fx)
    assert state.predecessors["txn::1792330800000-0000-phone-1"] == "txn::1792330400000-0000-tablet-b"
    (fork,) = state.forks
    assert fork.branches == (TAKE_A, TAKE_B) and fork.resolved_by is not None
    assert state.units["JKT-RAIN-M-BLU#001"].holder == "tablet-a"
    assert exceptions_for(state, "tablet-a", fx["trip"], fx["box"]) == []


def test_blind_take_with_no_predecessor_is_a_dangling_root_in_no_fork(fixture):
    state = state_of(fixture("null-root-take"))
    assert state.forks == ()
    assert state.predecessors["txn::1792329400000-0000-tablet-b"] is None
    assert state.units["JKT-RAIN-M-BLU#005"].holder == "tablet-b"
    assert state.untraced == frozenset()


def test_two_blind_takes_with_no_pack_never_fork(fixture):
    fx = fixture("null-root-take")
    (take,) = fx["transactions"]
    other = dict(take, _id="txn::1792329401000-0000-tablet-a", device="tablet-a",
                 hlc="1792329401000-0000-tablet-a", to_custodian="tablet-a")
    state = reduce([take, other], [], store=STORE)
    assert state.forks == ()
    assert state.units["JKT-RAIN-M-BLU#005"].last_txn == other["_id"]  # the leaf with the greatest hlc wins


def test_root_fork_between_the_pack_and_an_hq_sale(fixture):
    fx = fixture("oversell-hq")
    (fork,) = state_of(fx).forks
    assert fork.prev_txn is None
    assert fork.branches == (PACK_1, "txn::1792329100000-0000-hq")


def test_null_prev_check_in_never_joins_a_root_fork(fixture):
    state = state_of(fixture("unknown-unit-check-in"))
    assert state.forks == ()
    unit = state.units["HAT-BRIM-OS#004"]
    assert (unit.holder, unit.last_txn) == ("box-07", "txn::1792328900000-0000-tablet-b")


def test_duplicate_ids_collapse_whatever_the_order(fixture):
    fx = fixture("double-scan")
    doubled = fx["transactions"] + fx["transactions"][::-1]
    assert state_of(fx, transactions=doubled) == state_of(fx)


def test_a_prev_txn_cycle_terminates(fixture):
    """Malformed input (two movements naming each other) must not hang the reducer."""
    fx = fixture("double-scan")
    a, b = copy.deepcopy(fx["transactions"][1:])
    a["prev_txn"], b["prev_txn"] = b["_id"], a["_id"]
    state = reduce([a, b], [], store=STORE)
    assert set(state.units) == {"JKT-RAIN-M-BLU#001"}


# ---------------------------------------------------------------- contracts 0.4.0 (CC8, decision 006)

PHONE_TAKE = "txn::1792331000000-0000-phone-1"


def test_third_branch_reopens_a_settled_fork(fixture):
    """A resolution binds to the branches it was written for; a third branch is a fork it does not match."""
    fx = fixture("third-branch-at-resolved-fork")
    state = state_of(fx)
    (fork,) = state.forks
    assert fork.branches == (TAKE_A, TAKE_B, PHONE_TAKE)
    assert fork.resolved_by is None
    assert state.units["JKT-RAIN-M-BLU#001"].state == "disputed"
    (doc,) = exceptions_for(state, "tablet-a", fx["trip"], fx["box"])
    assert doc["transactions"] == [TAKE_A, TAKE_B, PHONE_TAKE]
    assert doc["_id"] != fx["resolutions"][0]["_id"]
    # Without the third branch the same resolution still settles the two-branch fork.
    two = state_of(fx, transactions=[t for t in fx["transactions"] if t["_id"] != PHONE_TAKE])
    assert two.forks[0].resolved_by == fx["resolutions"][0]["_id"]


def test_resolution_must_match_the_dispute_key(fixture):
    fx = fixture("resolved-fork")
    moved = copy.deepcopy(fx["resolutions"])
    moved[0]["dispute_key"] = "JKT-RAIN-M-BLU#001|root"
    state = state_of(fx, resolutions=moved)
    assert state.forks[0].resolved_by is None
    assert state.units["JKT-RAIN-M-BLU#001"].state == "disputed"


def test_fork_inside_a_set_aside_branch_is_not_reported(fixture):
    fx = fixture("fork-inside-set-aside-branch")
    state = state_of(fx)
    (fork,) = state.forks  # only the resolved fork at the pack
    assert fork.prev_txn == PACK_1 and fork.resolved_by == fx["resolutions"][0]["_id"]
    unit = state.units["JKT-RAIN-M-BLU#001"]
    assert (unit.holder, unit.state, unit.last_txn) == ("tablet-a", "held", TAKE_A)
    assert exceptions_for(state, "tablet-a", fx["trip"], fx["box"]) == []
    # Without the resolution both forks are reported and the unit is disputed.
    open_state = state_of(fx, resolutions=[])
    assert [f.prev_txn for f in open_state.forks] == [PACK_1, "txn::1792330400000-0000-tablet-b"]


def test_the_latest_resolution_settles_a_fork(fixture):
    fx = fixture("two-resolutions-one-fork")
    hq_copy, tablet_copy = fx["resolutions"]
    for order in ([hq_copy, tablet_copy], [tablet_copy, hq_copy]):
        state = state_of(fx, resolutions=order)
        assert state.forks[0].resolved_by == tablet_copy["_id"]  # 13:35 beats 13:30 although its _id sorts later
        assert state.units["JKT-RAIN-M-BLU#001"].holder == "tablet-b"
    # Equal resolution.at: the greatest _id decides.
    tie = copy.deepcopy([hq_copy, tablet_copy])
    tie[1]["resolution"]["at"] = tie[0]["resolution"]["at"]
    tie[0]["resolution"]["chosen_txn"], tie[1]["resolution"]["chosen_txn"] = TAKE_B, TAKE_A
    state = state_of(fx, resolutions=tie)
    assert state.forks[0].resolved_by == tablet_copy["_id"]
    assert state.units["JKT-RAIN-M-BLU#001"].holder == "tablet-a"


def test_resolution_naming_no_branch_settles_nothing(fixture):
    fx = fixture("resolution-without-choice")
    state = state_of(fx)
    assert state.forks[0].resolved_by is None
    assert state.units["JKT-RAIN-M-BLU#001"].state == "disputed"
    assert exceptions_for(state, "tablet-a", fx["trip"], fx["box"]) == []
    elsewhere = copy.deepcopy(fx["resolutions"])
    elsewhere[0]["resolution"]["chosen_txn"] = PACK_1  # a transaction, but not a branch
    assert state_of(fx, resolutions=elsewhere).units["JKT-RAIN-M-BLU#001"].state == "disputed"


def test_two_blind_takes_with_no_pack_fixture(fixture):
    state = state_of(fixture("null-root-double-take-no-pack"))
    assert state.forks == ()
    assert state.units["JKT-RAIN-M-BLU#001"].holder == "tablet-b"
