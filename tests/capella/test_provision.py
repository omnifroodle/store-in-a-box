import io

from siab_capella.__main__ import main
from siab_capella.config import ROOT, Config, read_dotenv
from siab_capella.gateway import Keyspace
from siab_capella.provision import COLLECTIONS, INDEXES, plan_provision


def test_provision_is_idempotent(cli, fake):
    code, out = cli("provision", "--yes")
    assert code == 0
    assert "provision: 15 change(s), 0 already in place" in out
    writes = len(fake.calls)
    assert writes == 15

    assert [s for s in plan_provision(fake) if s.change] == []
    code, out = cli("provision", "--yes")
    assert code == 0
    assert "provision: 0 change(s), 15 already in place" in out
    assert "nothing to do" in out
    assert len(fake.calls) == writes


def test_provision_creates_the_phase_0_layout(cli, fake):
    cli("provision", "--yes")
    assert set(fake.buckets["retail"]) == {"_default", "store", "agents", "ref"}
    assert fake.buckets["retail"]["store"] == set(COLLECTIONS)
    assert fake.buckets["retail"]["agents"] == set() and fake.buckets["retail"]["ref"] == set()
    assert fake.indexes["ix_txn_trip_unit"] == (Keyspace("retail", "store", "transaction"), ("trip", "unit_id", "hlc"))
    assert set(fake.indexes) == set(INDEXES)
    assert fake.calls[0] == ("ensure_bucket", "retail")  # bucket, then scopes, then collections, then indexes


def test_provision_completes_a_partial_layout(cli, fake):
    fake.buckets["retail"] = {"_default": {"_default"}, "store": {"product"}}
    code, out = cli("provision", "--yes")
    assert code == 0
    assert "provision: 12 change(s), 3 already in place" in out
    assert ("ensure_bucket", "retail") not in fake.calls
    assert ("ensure_collection", Keyspace("retail", "store", "product")) not in fake.calls


def test_provision_without_yes_writes_nothing(cli, fake):
    code, out = cli("provision")
    assert code == 0
    assert "re-run with --yes" in out
    assert fake.calls == []
    code, out = cli("provision", "--dry-run", "--yes")
    assert code == 0 and fake.calls == [] and "dry run: nothing written" in out


def _offline(*argv):
    """Run as `python -m siab_capella` would, with only the .env.example values (all empty) set."""
    out = io.StringIO()
    code = main(list(argv), config=Config(read_dotenv(ROOT / ".env.example")), out=out)
    return code, out.getvalue()


def test_provision_dry_run_plans_offline_with_only_env_example():
    code, out = _offline("provision", "--dry-run")
    assert code == 0
    assert "offline plan" in out
    assert "provision: 15 step(s) to ensure, current state unknown" in out
    assert "ensure    index ix_inv_store on retail.store.inventory(store, sku)" in out


def test_seed_dry_run_plans_offline_with_only_env_example():
    code, out = _offline("seed", "--dry-run")
    assert code == 0
    assert "seed: 33 step(s) to ensure" in out
    assert "retail.store.trip trip::trip-2026-10-18-riverfest" in out


def test_a_management_api_failure_is_reported_not_raised(cli, fake):
    from siab_capella.live import CapellaApiError

    def fail(*args, **kwargs):
        raise CapellaApiError("create bucket retail: HTTP 403 forbidden")

    fake.ensure_bucket = lambda bucket, *, apply: True if not apply else fail()
    code, out = cli("provision", "--yes")
    assert code == 1
    assert "CapellaApiError: create bucket retail: HTTP 403 forbidden" in out


def test_verify_dry_run_opens_no_session(cli, fake):
    code, out = cli("app-services", "verify", "--dry-run")
    assert code == 0 and "would connect to app endpoint store as box-07" in out


def test_without_credentials_and_without_dry_run_the_cli_refuses():
    code, out = _offline("provision", "--yes")
    assert code == 1
    assert "not set" in out and "--dry-run plans offline" in out
