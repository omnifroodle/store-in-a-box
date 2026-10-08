"""The live gateway: the Couchbase Python SDK for documents, queries and indexes; the Capella Management API v4 for
the bucket, scopes, collections and App Services; the App Services public REST API for `verify`.

Only the unit tests' fakes have exercised this module; the routes and payloads below are the ones task 3 (`[capella]`)
checks on the live cluster. Where App Services answers that a route does not exist (404, 405, 501) the gateway raises
ManualStepRequired with the steps to do in the Capella UI, and the CLI exits 2.
"""

from __future__ import annotations

import base64
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import httpx

from .config import Config
from .gateway import Channels, EndpointState, Keyspace, ManualStepRequired

API_BASE = "https://cloudapi.cloud.couchbase.com"  # the public Capella Management API (not an account host)
BUCKET_SETTINGS = {"type": "couchbase", "memoryAllocationInMb": 100}  # the API's defaults for everything else
NOT_THERE = (404, 405, 501)


class CapellaApiError(RuntimeError):
    pass


def http_base(public_url: str) -> str:
    """APP_SERVICES_PUBLIC_URL is the replication URL (wss://.../<endpoint>); its REST base is the https form."""
    if public_url.startswith("wss://"):
        return "https://" + public_url.removeprefix("wss://").rstrip("/")
    if public_url.startswith("ws://"):
        return "http://" + public_url.removeprefix("ws://").rstrip("/")
    return public_url.rstrip("/")


def session_channels(body: dict[str, Any], scope: str, collections: list[str]) -> Channels:
    """Channels per collection from a `_session` response. A per-collection view (`collection_access`) is used when
    the response has one; otherwise the user-level `channels` are reported for every collection."""
    ctx = body.get("userCtx") or {}
    per = (ctx.get("collection_access") or {}).get(scope)
    if per is not None:
        return {c: sorted((per.get(c) or {}).get("all_channels") or (per.get(c) or {}).get("admin_channels") or [])
                for c in collections}
    return {c: sorted(ctx.get("channels") or []) for c in collections}


class LiveCapella:
    def __init__(self, config: Config, *, transport: httpx.BaseTransport | None = None, cluster: Any = None) -> None:
        self.config = config
        self._transport = transport  # tests pass a mock; None is the network
        self._http: httpx.Client | None = None
        self._public: httpx.Client | None = None
        self._cluster = cluster

    # ------------------------------------------------------------------ clients (opened on first use)

    @property
    def api(self) -> httpx.Client:
        if self._http is None:
            key = self.config.get("CAPELLA_API_KEY")
            self._http = httpx.Client(base_url=API_BASE, headers={"Authorization": f"Bearer {key}"}, timeout=60,
                                      transport=self._transport)
        return self._http

    @property
    def cluster(self) -> Any:
        if self._cluster is None:
            from couchbase.auth import PasswordAuthenticator
            from couchbase.cluster import Cluster
            from couchbase.options import ClusterOptions

            opts = ClusterOptions(PasswordAuthenticator(self.config.get("CAPELLA_DB_USERNAME"),
                                                        self.config.get("CAPELLA_DB_PASSWORD")))
            opts.apply_profile("wan_development")
            self._cluster = Cluster(self.config.get("CAPELLA_CONN_STRING"), opts)
            self._cluster.wait_until_ready(timedelta(seconds=30))
        return self._cluster

    def _cluster_path(self) -> str:
        c = self.config
        return (f"/v4/organizations/{c.get('CAPELLA_ORG_ID')}/projects/{c.get('CAPELLA_PROJECT_ID')}"
                f"/clusters/{c.get('CAPELLA_CLUSTER_ID')}")

    def _app_path(self) -> str:
        return f"{self._cluster_path()}/appservices/{self.config.get('CAPELLA_APP_SERVICE_ID')}/appEndpoints"

    def _call(self, method: str, path: str, what: str, *, ok_missing: bool = False, **kw: Any) -> httpx.Response:
        """One Management API call. Errors name the operation, never the URL (it carries account ids)."""
        r = self.api.request(method, path, **kw)
        if r.is_success or (ok_missing and r.status_code in NOT_THERE):
            return r
        try:
            message = r.json().get("message", "")
        except ValueError:
            message = r.text[:200]
        raise CapellaApiError(f"{what}: HTTP {r.status_code} {message}".rstrip())

    # ------------------------------------------------------------------ cluster structure

    @staticmethod
    def _bucket_id(bucket: str) -> str:
        return quote(base64.b64encode(bucket.encode()).decode(), safe="")

    def _scopes(self, bucket: str) -> dict[str, set[str]] | None:
        r = self._call("GET", f"{self._cluster_path()}/buckets/{self._bucket_id(bucket)}/scopes", "list scopes",
                       ok_missing=True)
        if r.status_code in NOT_THERE:
            return None
        return {s["name"]: {c["name"] for c in s.get("collections") or []} for s in r.json().get("scopes") or []}

    def ensure_bucket(self, bucket: str, *, apply: bool) -> bool:
        r = self._call("GET", f"{self._cluster_path()}/buckets", "list buckets")
        if bucket in {b["name"] for b in r.json().get("data") or []}:
            return False
        if apply:
            self._call("POST", f"{self._cluster_path()}/buckets", f"create bucket {bucket}",
                       json={"name": bucket, **BUCKET_SETTINGS})
        return True

    def ensure_scope(self, bucket: str, scope: str, *, apply: bool) -> bool:
        if scope in (self._scopes(bucket) or {}):
            return False
        if apply:
            self._call("POST", f"{self._cluster_path()}/buckets/{self._bucket_id(bucket)}/scopes",
                       f"create scope {bucket}.{scope}", json={"name": scope})
        return True

    def ensure_collection(self, ks: Keyspace, *, apply: bool) -> bool:
        if ks.collection in (self._scopes(ks.bucket) or {}).get(ks.scope, set()):
            return False
        if apply:
            self._call("POST", f"{self._cluster_path()}/buckets/{self._bucket_id(ks.bucket)}/scopes/{ks.scope}"
                       "/collections", f"create collection {ks}", json={"name": ks.collection})
        return True

    def ensure_index(self, name: str, ks: Keyspace, fields: tuple[str, ...], *, apply: bool) -> bool:
        found = self.query("SELECT RAW i.name FROM system:indexes AS i WHERE i.bucket_id = $b AND i.scope_id = $s "
                           "AND i.keyspace_id = $c AND i.name = $n",
                           {"b": ks.bucket, "s": ks.scope, "c": ks.collection, "n": name})
        if found:
            return False
        if apply:
            keys = ", ".join(f"`{f}`" for f in fields)
            self.query(f"CREATE INDEX `{name}` IF NOT EXISTS ON {ks.sqlpp()}({keys})", {})
        return True

    # ------------------------------------------------------------------ documents

    def _coll(self, ks: Keyspace) -> Any:
        return self.cluster.bucket(ks.bucket).scope(ks.scope).collection(ks.collection)

    def get(self, ks: Keyspace, doc_id: str) -> dict[str, Any] | None:
        from couchbase.exceptions import DocumentNotFoundException

        try:
            return self._coll(ks).get(doc_id).content_as[dict]
        except DocumentNotFoundException:
            return None

    def upsert(self, ks: Keyspace, doc_id: str, doc: dict[str, Any]) -> None:
        self._coll(ks).upsert(doc_id, doc)

    def delete(self, ks: Keyspace, doc_id: str) -> None:
        from couchbase.exceptions import DocumentNotFoundException

        try:
            self._coll(ks).remove(doc_id)
        except DocumentNotFoundException:
            pass  # already gone: a delete is idempotent

    def query(self, statement: str, params: dict[str, Any]) -> list[Any]:
        from couchbase.options import QueryOptions

        return list(self.cluster.query(statement, QueryOptions(named_parameters=params)).rows())

    # ------------------------------------------------------------------ App Services

    def app_services_get_endpoint(self, name: str) -> EndpointState | None:
        r = self._call("GET", f"{self._app_path()}/{name}", f"get app endpoint {name}", ok_missing=True)
        if r.status_code in NOT_THERE:
            return None
        body = r.json()
        scopes = body.get("scopes") or {}
        scope = next(iter(scopes), "")
        colls = (scopes.get(scope) or {}).get("collections") or {}
        return EndpointState(body.get("bucket", ""), scope,
                             {c: (v or {}).get("accessControlFunction") or "" for c, v in colls.items()})

    def app_services_create_endpoint(self, name: str, bucket: str, scope: str, functions: dict[str, str]) -> None:
        body = {"name": name, "bucket": bucket, "deltaSyncEnabled": True,
                "scopes": {scope: {"collections": {c: {"accessControlFunction": f} for c, f in functions.items()}}}}
        r = self._call("POST", self._app_path(), f"create app endpoint {name}", ok_missing=True, json=body)
        if r.status_code in NOT_THERE:
            raise ManualStepRequired([f"Create app endpoint {name} on bucket {bucket}, scope {scope}, linking "
                                      f"{', '.join(functions)} (App Services > Create App Endpoint)."])

    def app_services_link_collection(self, name: str, scope: str, collection: str, function: str) -> None:
        # Linking a collection to an existing endpoint takes the endpoint offline; it is left to the UI on purpose.
        raise ManualStepRequired([f"Link {scope}.{collection} to app endpoint {name} (App Services > {name} > "
                                  "Settings > Linked collections), then resume the endpoint."])

    def app_services_set_sync_function(self, name: str, scope: str, collection: str, function: str) -> None:
        r = self._call("PUT", f"{self._app_path()}/{name}.{scope}.{collection}/accessControlFunction",
                       f"set access control function {name} > {scope}.{collection}", ok_missing=True,
                       content=function.encode(), headers={"Content-Type": "application/javascript"})
        if r.status_code in NOT_THERE:
            raise ManualStepRequired([f"Open App Services > {name} > Access and validation > {scope}.{collection}."])

    def app_services_get_users(self, name: str) -> dict[str, Channels]:
        r = self._call("GET", f"{self._app_path()}/{name}/users", f"list users of {name}", ok_missing=True)
        if r.status_code in NOT_THERE:
            return {}
        rows = r.json()
        rows = rows.get("data", []) if isinstance(rows, dict) else rows
        out: dict[str, Channels] = {}
        for u in rows:
            access = u.get("access") or {}
            out[u["name"]] = {c: sorted(ch) for scope in access.values() for c, ch in (scope or {}).items()}
        return out

    def app_services_put_user(self, name: str, scope: str, user: str, channels: Channels,
                              password: str | None) -> None:
        body: dict[str, Any] = {"access": {scope: channels}}
        if password is not None:
            body["password"] = password
        if password is not None and user not in self.app_services_get_users(name):
            r = self._call("POST", f"{self._app_path()}/{name}/users", f"create user {user}", ok_missing=True,
                           json={"name": user, **body})
        else:
            r = self._call("PUT", f"{self._app_path()}/{name}/users/{user}", f"update user {user}", ok_missing=True,
                           json=body)
        if r.status_code in NOT_THERE:
            grant = "; ".join(f"{scope}.{c}: {', '.join(ch)}" for c, ch in channels.items())
            raise ManualStepRequired([f"App Services > {name} > App Users: create or edit user {user} (password from "
                                      f".env) and grant {grant}."])

    def app_services_session(self, user: str, password: str, scope: str, collections: list[str]) -> Channels:
        if self._public is None:
            self._public = httpx.Client(base_url=http_base(self.config.get("APP_SERVICES_PUBLIC_URL")), timeout=30,
                                        transport=self._transport)
        r = self._public.get("/_session", auth=(user, password))
        if r.status_code in (401, 403):
            raise PermissionError(f"App Services refused the session for {user} (HTTP {r.status_code})")
        if not r.is_success:
            raise CapellaApiError(f"session as {user}: HTTP {r.status_code}")
        body = r.json()
        if (body.get("userCtx") or {}).get("name") != user:
            raise PermissionError(f"the session is not {user}'s (a guest session?)")
        return session_channels(body, scope, collections)
