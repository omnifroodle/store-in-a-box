"""LiveCapella's request shapes against mocked transports: no network. These pin what the code sends; whether
Capella accepts it is task 3's live check (needs-verification)."""

import json

import httpx
import pytest

from siab_capella.config import Config
from siab_capella.gateway import Keyspace, ManualStepRequired
from siab_capella.live import LiveCapella, http_base, session_channels

ENV = {"CAPELLA_ORG_ID": "org", "CAPELLA_PROJECT_ID": "proj", "CAPELLA_CLUSTER_ID": "clu",
       "CAPELLA_APP_SERVICE_ID": "app", "CAPELLA_API_KEY": "test-key", "CAPELLA_API_BASE": "http://api.test",
       "APP_SERVICES_PUBLIC_URL": "wss://app-services.test:4984/store"}
CP = "/v4/organizations/org/projects/proj/clusters/clu"
EP = f"{CP}/appservices/app/appEndpoints"


class Api:
    """A scripted Management API: routes[(method, path)] -> (status, json body); records requests."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.routes.get((request.method, request.url.path), (404, {"message": "not found"}))
        return httpx.Response(status, json=body)


def live(routes, **kw):
    api = Api(routes)
    return LiveCapella(Config(ENV), transport=httpx.MockTransport(api), **kw), api


def test_ensure_bucket_checks_then_creates():
    gw, api = live({("GET", f"{CP}/buckets"): (200, {"data": [{"name": "other"}]}),
                    ("POST", f"{CP}/buckets"): (201, {"id": "cmV0YWls"})})
    assert gw.ensure_bucket("retail", apply=False) is True
    assert [r.method for r in api.requests] == ["GET"]
    assert gw.ensure_bucket("retail", apply=True) is True
    assert json.loads(api.requests[-1].content)["name"] == "retail"
    assert api.requests[-1].headers["Authorization"] == "Bearer test-key"


def test_scopes_and_collections_use_the_base64_bucket_id():
    scopes = {"scopes": [{"name": "store", "collections": [{"name": "product"}]}]}
    gw, api = live({("GET", f"{CP}/buckets/cmV0YWls/scopes"): (200, scopes),
                    ("POST", f"{CP}/buckets/cmV0YWls/scopes"): (201, {}),
                    ("POST", f"{CP}/buckets/cmV0YWls/scopes/store/collections"): (201, {})})
    assert gw.ensure_scope("retail", "store", apply=True) is False
    assert gw.ensure_scope("retail", "agents", apply=True) is True
    assert json.loads(api.requests[-1].content) == {"name": "agents"}
    assert gw.ensure_collection(Keyspace("retail", "store", "product"), apply=True) is False
    assert gw.ensure_collection(Keyspace("retail", "store", "trip"), apply=True) is True
    assert json.loads(api.requests[-1].content) == {"name": "trip"}


def test_a_missing_bucket_means_missing_scopes():
    gw, _ = live({})
    assert gw.ensure_scope("retail", "store", apply=False) is True


def test_api_errors_name_the_operation_not_the_url():
    gw, _ = live({("GET", f"{CP}/buckets"): (403, {"message": "forbidden"})})
    with pytest.raises(RuntimeError) as e:
        gw.ensure_bucket("retail", apply=False)
    assert str(e.value) == "list buckets: HTTP 403 forbidden"


class Cluster:
    def __init__(self, rows):
        self.rows_ = rows
        self.statements = []

    def query(self, statement, options):
        self.statements.append(statement)
        rows = self.rows_.pop(0) if self.rows_ else []

        class Result:
            def rows(self):
                return iter(rows)

        return Result()


def test_ensure_index_escapes_the_reserved_keyspace():
    cluster = Cluster([[], []])
    gw, _ = live({}, cluster=cluster)
    assert gw.ensure_index("ix_txn_trip_hlc", Keyspace("retail", "store", "transaction"), ("trip", "hlc"),
                           apply=True) is True
    assert cluster.statements[1] == ("CREATE INDEX `ix_txn_trip_hlc` IF NOT EXISTS ON "
                                     "`retail`.`store`.`transaction`(`trip`, `hlc`)")
    cluster = Cluster([["ix_txn_trip_hlc"]])
    gw, _ = live({}, cluster=cluster)
    assert gw.ensure_index("ix_txn_trip_hlc", Keyspace("retail", "store", "transaction"), ("trip", "hlc"),
                           apply=True) is False
    assert len(cluster.statements) == 1


def test_get_endpoint_reads_functions_per_collection():
    body = {"name": "store", "bucket": "retail",
            "scopes": {"store": {"collections": {"trip": {"accessControlFunction": "function (doc) {}"}}}}}
    gw, _ = live({("GET", f"{EP}/store"): (200, body)})
    ep = gw.app_services_get_endpoint("store")
    assert (ep.bucket, ep.scope, ep.functions) == ("retail", "store", {"trip": "function (doc) {}"})
    gw, _ = live({})
    assert gw.app_services_get_endpoint("store") is None


def test_create_endpoint_sends_every_function():
    gw, api = live({("POST", EP): (201, {})})
    gw.app_services_create_endpoint("store", "retail", "store", {"trip": "T", "product": "P"})
    sent = json.loads(api.requests[-1].content)
    assert sent["scopes"]["store"]["collections"] == {"trip": {"accessControlFunction": "T"},
                                                      "product": {"accessControlFunction": "P"}}


def test_routes_the_api_lacks_become_manual_steps():
    gw, _ = live({})
    with pytest.raises(ManualStepRequired):
        gw.app_services_create_endpoint("store", "retail", "store", {"trip": "T"})
    with pytest.raises(ManualStepRequired):
        gw.app_services_set_sync_function("store", "store", "trip", "T")
    with pytest.raises(ManualStepRequired):
        gw.app_services_link_collection("store", "store", "trip", "T")
    with pytest.raises(ManualStepRequired, match="grant store.trip: trip:t"):
        gw.app_services_put_user("store", "store", "box-07", {"trip": ["trip:t"]}, "pw")


def test_set_sync_function_puts_the_source():
    gw, api = live({("PUT", f"{EP}/store.store.trip/accessControlFunction"): (200, {})})
    gw.app_services_set_sync_function("store", "store", "trip", "function (doc) {}")
    assert api.requests[-1].content == b"function (doc) {}"


def test_users_create_then_update_without_password():
    users = [{"name": "hq", "access": {"store": {"trip": ["*"]}}}]
    gw, api = live({("GET", f"{EP}/store/users"): (200, users), ("POST", f"{EP}/store/users"): (201, {}),
                    ("PUT", f"{EP}/store/users/hq"): (200, {})})
    assert gw.app_services_get_users("store") == {"hq": {"trip": ["*"]}}
    gw.app_services_put_user("store", "store", "box-07", {"trip": ["trip:t"]}, "pw")
    assert json.loads(api.requests[-1].content) == {"name": "box-07", "password": "pw",
                                                    "access": {"store": {"trip": ["trip:t"]}}}
    gw.app_services_put_user("store", "store", "hq", {"trip": ["*"]}, None)
    assert api.requests[-1].method == "PUT" and "password" not in json.loads(api.requests[-1].content)


def test_session_reads_channels_and_refuses_a_guest():
    def handler(request):
        assert request.url.path == "/store/_session"
        if request.headers.get("Authorization") is None:
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True, "userCtx": {"name": "box-07",
                                                                 "channels": {"!": 1, "trip:t": 3}}})

    gw = LiveCapella(Config(ENV), transport=httpx.MockTransport(handler))
    assert gw.app_services_session("box-07", "pw", "store", ["trip", "product"]) == {"trip": ["!", "trip:t"],
                                                                                     "product": ["!", "trip:t"]}
    with pytest.raises(PermissionError):
        gw.app_services_session("hq", "pw", "store", ["trip"])


def test_session_channels_prefers_a_per_collection_view():
    body = {"userCtx": {"name": "box-07", "channels": {"!": 1},
                        "collection_access": {"store": {"trip": {"all_channels": {"trip:t": 1}}}}}}
    assert session_channels(body, "store", ["trip", "product"]) == {"trip": ["trip:t"], "product": []}


def test_http_base():
    assert http_base("wss://h.test:4984/store/") == "https://h.test:4984/store"
    assert http_base("ws://h.test/store") == "http://h.test/store"
