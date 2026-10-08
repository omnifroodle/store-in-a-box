from siab_capella.gateway import Keyspace

TRIP = "trip-2026-10-18-riverfest"
OTHER = "trip-2026-11-01-other"


def ks(c):
    return Keyspace("retail", "store", c)


def _venue_docs(fake):
    fake.docs = {
        ks("allocation"): {"alloc::1": {"trip": TRIP}, "alloc::2": {"trip": OTHER}},
        ks("transaction"): {"txn::1": {"trip": TRIP}, "txn::2": {"trip": TRIP}, "txn::3": {"trip": OTHER}},
        ks("exception"): {"exc::1": {"trip": TRIP}},
        ks("product"): {"product::X": {"trip": TRIP}},  # never touched: not a venue collection
        ks("trip"): {f"trip::{TRIP}": {"trip_id": TRIP}},
    }


def test_reset_trip_refuses_without_yes(cli, fake):
    _venue_docs(fake)
    code, out = cli("reset-trip", "--trip", TRIP)
    assert code == 1
    assert "refusing without --yes" in out
    assert fake.calls == []
    assert len(fake.docs[ks("transaction")]) == 3


def test_reset_trip_dry_run_lists_the_deletes(cli, fake):
    _venue_docs(fake)
    code, out = cli("reset-trip", "--trip", TRIP, "--dry-run")
    assert code == 0
    assert "reset-trip trip-2026-10-18-riverfest: 4 change(s)" in out
    assert "delete    retail.store.transaction txn::2" in out
    assert fake.calls == []


def test_reset_trip_deletes_only_that_trips_venue_documents(cli, fake):
    _venue_docs(fake)
    code, out = cli("reset-trip", "--trip", TRIP, "--yes")
    assert code == 0
    assert sorted(c[2] for c in fake.calls) == ["alloc::1", "exc::1", "txn::1", "txn::2"]
    assert fake.docs[ks("allocation")] == {"alloc::2": {"trip": OTHER}}
    assert fake.docs[ks("transaction")] == {"txn::3": {"trip": OTHER}}
    assert fake.docs[ks("exception")] == {}
    assert len(fake.docs[ks("product")]) == 1 and len(fake.docs[ks("trip")]) == 1

    code, out = cli("reset-trip", "--trip", TRIP, "--yes")
    assert code == 0 and "nothing to do" in out


def test_reset_trip_requires_a_trip(cli):
    import pytest

    with pytest.raises(SystemExit):
        cli("reset-trip", "--yes")
