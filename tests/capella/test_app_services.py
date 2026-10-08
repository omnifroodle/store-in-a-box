import json

import pytest

from siab_capella.app_services import load_endpoint, plan_app_services
from siab_capella.config import ROOT, SEED_DIR, SYNC_DIR, Config
from siab_capella.gateway import EndpointState

PASSWORDS = {"BOX_APP_PASSWORD": "test-box-password", "HQ_APP_PASSWORD": "test-hq-password"}  # as in conftest.py
LINKED = ["product", "trip", "allocation", "transaction", "exception"]


def test_app_endpoint_json_matches_fixture_users():
    spec = json.loads((SYNC_DIR / "app-endpoint.json").read_text())
    registry = json.loads((SEED_DIR / "custodians.json").read_text())
    want = {c["app_services_user"]: sorted(c["channels"]) for c in registry if "app_services_user" in c}
    got = {u["name"]: sorted(u["channels"]) for u in spec["users"]}
    assert got == want


def test_app_endpoint_json_names_the_blueprint_endpoint():
    spec = load_endpoint(SYNC_DIR)
    assert (spec["name"], spec["bucket"], spec["scope"]) == ("store", "retail", "store")
    assert sorted(spec["functions"]) == sorted(LINKED)  # never inventory
    for c, path in spec["collections"].items():
        assert path == f"functions/store.{c}.js"
        assert spec["functions"][c].startswith("function (doc, oldDoc, meta) {")
    assert not any("password" in k and k != "password_env" for u in spec["users"] for k in u)  # no secrets in it


def test_load_endpoint_refuses_to_link_inventory(tmp_path):
    spec = json.loads((SYNC_DIR / "app-endpoint.json").read_text())
    spec["collections"]["inventory"] = "functions/store.product.js"
    (tmp_path / "functions").mkdir()
    (tmp_path / "functions" / "store.product.js").write_text("function (doc, oldDoc, meta) {}\n")
    for c in LINKED:
        (tmp_path / "functions" / f"store.{c}.js").write_text("function (doc, oldDoc, meta) {}\n")
    (tmp_path / "app-endpoint.json").write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="inventory"):
        load_endpoint(tmp_path)


def test_apply_creates_endpoint_and_users_then_is_idempotent(cli, fake):
    code, out = cli("app-services", "apply", "--yes")
    assert code == 0, out
    ep = fake.endpoints["store"]
    assert (ep.bucket, ep.scope) == ("retail", "store")
    assert ep.functions == {c: (SYNC_DIR / f"functions/store.{c}.js").read_text() for c in LINKED}
    assert fake.users["store"]["box-07"] == {c: sorted(["trip:trip-2026-10-18-riverfest", "catalog:va-central",
                                                        "box:box-07"]) for c in LINKED}
    assert fake.users["store"]["hq"] == {c: ["*"] for c in LINKED}
    assert fake.passwords == {"box-07": PASSWORDS["BOX_APP_PASSWORD"], "hq": PASSWORDS["HQ_APP_PASSWORD"]}
    calls = len(fake.calls)

    code, out = cli("app-services", "apply", "--yes")
    assert code == 0 and "nothing to do" in out and len(fake.calls) == calls


def test_apply_updates_a_drifted_function_and_user(cli, fake):
    cli("app-services", "apply", "--yes")
    fake.endpoints["store"].functions["trip"] = "function (doc) { channel('!'); }"
    fake.users["store"]["box-07"]["trip"] = ["box:box-07"]
    code, out = cli("app-services", "apply")
    assert "update    sync function store > store.trip" in out
    assert "update    user box-07 on store" in out
    code, out = cli("app-services", "apply", "--yes")
    assert code == 0
    assert fake.endpoints["store"].functions["trip"] == (SYNC_DIR / "functions/store.trip.js").read_text()
    assert ("app_services_put_user", "store", "box-07") in fake.calls
    assert fake.passwords["box-07"] == PASSWORDS["BOX_APP_PASSWORD"]  # an update keeps the password


def test_apply_prints_manual_steps_and_function_body_and_exits_2(cli, fake):
    fake.manual = {"app_services_create_endpoint"}
    code, out = cli("app-services", "apply", "--yes")
    assert code == 2
    assert "Manual steps" in out
    assert "Paste as the access control function of store > store.transaction" in out
    assert (SYNC_DIR / "functions/store.transaction.js").read_text().rstrip() in out


def test_apply_links_a_missing_collection(cli, fake):
    cli("app-services", "apply", "--yes")
    del fake.endpoints["store"].functions["exception"]
    fake.manual = {"app_services_link_collection"}
    code, out = cli("app-services", "apply", "--yes")
    assert code == 2
    assert "create    link store.exception to store" in out
    assert "store > store.exception (sync/functions/store.exception.js)" in out


def test_apply_flags_a_linked_inventory(cli, fake):
    cli("app-services", "apply", "--yes")
    fake.endpoints["store"].functions["inventory"] = ""
    code, out = cli("app-services", "apply", "--yes")
    assert code == 2
    assert "Unlink store.inventory from app endpoint store" in out


def test_apply_flags_an_endpoint_over_another_scope(cli, fake):
    fake.endpoints["store"] = EndpointState("retail", "agents", {})
    code, out = cli("app-services", "apply", "--yes")
    assert code == 2 and "is over retail.agents" in out


def test_apply_refuses_to_create_a_user_without_its_password(cli, fake):
    code, out = cli("app-services", "apply", "--yes", env={"HQ_APP_PASSWORD": "x"})
    assert code == 1
    assert "BOX_APP_PASSWORD is not set" in out
    assert fake.calls == []


def test_apply_refuses_env_that_contradicts_the_endpoint(cli, fake):
    code, out = cli("app-services", "apply", "--yes", env={**PASSWORDS, "BOX_APP_USER": "box-99",
                                                           "SIAB_TRIP": "trip-2026-11-01-other"})
    assert code == 1
    assert "BOX_APP_USER=box-99" in out and "SIAB_TRIP=trip-2026-11-01-other" in out
    assert fake.calls == []
    code, _ = cli("app-services", "apply", "--yes", env={**PASSWORDS, "BOX_APP_USER": "box-07",
                                                         "SIAB_TRIP": "trip-2026-10-18-riverfest",
                                                         "SIAB_REGION": "va-central"})
    assert code == 0


def test_apply_dry_run_offline(cli):
    code, out = cli("app-services", "apply", "--dry-run", env={}, gateway=None)
    assert code == 0
    assert "app-services apply (store): 8 step(s) to ensure" in out


def test_verify_exits_0_on_the_expected_channels(cli, fake):
    cli("app-services", "apply", "--yes")
    code, out = cli("app-services", "verify")
    assert code == 0, out
    assert "session as box-07 on store: ok" in out
    assert "channels as expected" in out
    assert fake.calls[-1][0] == "app_services_put_user"  # verify wrote nothing


def test_verify_ignores_the_public_channel(cli, fake):
    cli("app-services", "apply", "--yes")
    for c in LINKED:
        fake.users["store"]["box-07"][c].append("!")
    assert cli("app-services", "verify")[0] == 0


def test_verify_exits_1_on_a_missing_grant(cli, fake):
    cli("app-services", "apply", "--yes")
    fake.users["store"]["box-07"]["allocation"] = ["box:box-07"]
    code, out = cli("app-services", "verify")
    assert code == 1
    assert "allocation: granted ['box:box-07']" in out


def test_verify_exits_1_on_a_refused_session(cli, fake):
    cli("app-services", "apply", "--yes")
    code, out = cli("app-services", "verify", env={**PASSWORDS, "BOX_APP_PASSWORD": "wrong"})
    assert code == 1 and "failed: PermissionError" in out
    code, out = cli("app-services", "verify", env={})
    assert code == 1 and "BOX_APP_PASSWORD is not set" in out


def test_plan_offline_has_no_runs():
    steps = plan_app_services(None, load_endpoint(SYNC_DIR), Config({}))
    assert steps and all(s.action == "ensure" and s.run is None for s in steps)


def test_env_example_lists_exactly_the_contract_names():
    from siab_capella.config import ENV_VARS, read_dotenv

    example = read_dotenv(ROOT / ".env.example")
    assert list(example) == list(ENV_VARS)
    assert set(example.values()) == {""}  # names only, never values
    port = (ROOT / "ports" / "capella.md").read_text()
    assert all(f"`{n}`" in port for n in ENV_VARS)
