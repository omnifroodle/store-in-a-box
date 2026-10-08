"""The Capella gateway port (ports/capella.md): what the CLI (and WS5's reads) need from the cluster and App Services.

`CapellaGateway` is the protocol; `FakeCapella` is an in-memory implementation that records every write, for unit
tests. The live implementation is `siab_capella.live.LiveCapella`.

Every `ensure_*` takes `apply`: with `apply=False` it only checks, and returns True when the thing is missing (a
change is needed); with `apply=True` it also creates it, and returns True when it did.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol


class Keyspace(NamedTuple):
    bucket: str
    scope: str
    collection: str

    def __str__(self) -> str:
        return f"{self.bucket}.{self.scope}.{self.collection}"

    def sqlpp(self) -> str:
        """The keyspace for SQL++, every part escaped (`transaction` is a reserved word)."""
        return ".".join(f"`{p}`" for p in self)


class ManualStepRequired(Exception):  # noqa: N818 (a signal, not an error: the CLI prints the steps and exits 2)
    """The Management API does not cover this step; `steps` are the exact instructions for the Capella UI."""

    def __init__(self, steps: list[str]):
        super().__init__("; ".join(steps))
        self.steps = steps


@dataclass
class EndpointState:
    """An App Endpoint as App Services reports it: what it is over and each linked collection's sync function."""

    bucket: str
    scope: str
    functions: dict[str, str] = field(default_factory=dict)  # collection -> sync function source


Channels = dict[str, list[str]]  # collection -> channels


class CapellaGateway(Protocol):
    # Cluster structure.
    def ensure_bucket(self, bucket: str, *, apply: bool) -> bool: ...
    def ensure_scope(self, bucket: str, scope: str, *, apply: bool) -> bool: ...
    def ensure_collection(self, ks: Keyspace, *, apply: bool) -> bool: ...
    def ensure_index(self, name: str, ks: Keyspace, fields: tuple[str, ...], *, apply: bool) -> bool: ...

    # Documents (the Data Service, as the cluster database credential).
    def get(self, ks: Keyspace, doc_id: str) -> dict[str, Any] | None: ...
    def upsert(self, ks: Keyspace, doc_id: str, doc: dict[str, Any]) -> None: ...
    def delete(self, ks: Keyspace, doc_id: str) -> None: ...
    def query(self, statement: str, params: dict[str, Any]) -> list[Any]: ...

    # App Services (may raise ManualStepRequired where the Management API does not reach).
    def app_services_get_endpoint(self, name: str) -> EndpointState | None: ...
    def app_services_create_endpoint(self, name: str, bucket: str, scope: str, functions: dict[str, str]) -> None: ...
    def app_services_link_collection(self, name: str, scope: str, collection: str, function: str) -> None: ...
    def app_services_set_sync_function(self, name: str, scope: str, collection: str, function: str) -> None: ...
    def app_services_get_users(self, name: str) -> dict[str, Channels]: ...
    def app_services_put_user(self, name: str, scope: str, user: str, channels: Channels,
                              password: str | None) -> None: ...
    def app_services_session(self, user: str, password: str, scope: str, collections: list[str]) -> Channels:
        """Connect to the public endpoint as `user`; the channels it is granted on each of `collections`."""
        ...


_ID_BY_FIELD = re.compile(
    r"^SELECT RAW META\(d\)\.id FROM (?P<ks>`[^`]+`\.`[^`]+`\.`[^`]+`) AS d WHERE d\.`(?P<field>\w+)` = \$(?P<p>\w+)$"
)


class FakeCapella:
    """In-memory Capella. `calls` records every write as a tuple; `manual` names App Services methods that raise
    ManualStepRequired, as the live gateway does where the Management API stops. `query` understands the one shape the
    CLI issues (ids by a field); tests needing more set `query_handler`."""

    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, set[str]]] = {}  # bucket -> scope -> collections
        self.indexes: dict[str, tuple[Keyspace, tuple[str, ...]]] = {}
        self.docs: dict[Keyspace, dict[str, dict[str, Any]]] = {}
        self.endpoints: dict[str, EndpointState] = {}
        self.users: dict[str, dict[str, Channels]] = {}  # endpoint -> user -> channels
        self.passwords: dict[str, str] = {}
        self.calls: list[tuple[Any, ...]] = []
        self.manual: set[str] = set()
        self.query_handler = None

    def _write(self, *call: Any) -> None:
        self.calls.append(call)
        if call[0] in self.manual:
            raise ManualStepRequired([f"{call[0]} {call[1:]!r} by hand in the Capella UI"])

    # Cluster structure.
    def ensure_bucket(self, bucket: str, *, apply: bool) -> bool:
        if bucket in self.buckets:
            return False
        if apply:
            self._write("ensure_bucket", bucket)
            self.buckets[bucket] = {"_default": {"_default"}}
        return True

    def ensure_scope(self, bucket: str, scope: str, *, apply: bool) -> bool:
        if scope in self.buckets.get(bucket, {}):
            return False
        if apply:
            self._write("ensure_scope", bucket, scope)
            self.buckets[bucket][scope] = set()
        return True

    def ensure_collection(self, ks: Keyspace, *, apply: bool) -> bool:
        if ks.collection in self.buckets.get(ks.bucket, {}).get(ks.scope, set()):
            return False
        if apply:
            self._write("ensure_collection", ks)
            self.buckets[ks.bucket][ks.scope].add(ks.collection)
        return True

    def ensure_index(self, name: str, ks: Keyspace, fields: tuple[str, ...], *, apply: bool) -> bool:
        if name in self.indexes:
            return False
        if apply:
            self._write("ensure_index", name, ks, fields)
            self.indexes[name] = (ks, fields)
        return True

    # Documents.
    def get(self, ks: Keyspace, doc_id: str) -> dict[str, Any] | None:
        doc = self.docs.get(ks, {}).get(doc_id)
        return copy.deepcopy(doc) if doc is not None else None

    def upsert(self, ks: Keyspace, doc_id: str, doc: dict[str, Any]) -> None:
        self._write("upsert", ks, doc_id)
        self.docs.setdefault(ks, {})[doc_id] = copy.deepcopy(doc)

    def delete(self, ks: Keyspace, doc_id: str) -> None:
        self._write("delete", ks, doc_id)
        self.docs.get(ks, {}).pop(doc_id, None)

    def query(self, statement: str, params: dict[str, Any]) -> list[Any]:
        if self.query_handler is not None:
            return self.query_handler(statement, params)
        m = _ID_BY_FIELD.match(statement)
        if not m:
            raise NotImplementedError(f"FakeCapella.query does not understand: {statement}")
        ks = Keyspace(*(p.strip("`") for p in m["ks"].split(".")))
        value = params[m["p"]]
        return sorted(i for i, d in self.docs.get(ks, {}).items() if d.get(m["field"]) == value)

    # App Services.
    def app_services_get_endpoint(self, name: str) -> EndpointState | None:
        return copy.deepcopy(self.endpoints.get(name))

    def app_services_create_endpoint(self, name: str, bucket: str, scope: str, functions: dict[str, str]) -> None:
        self._write("app_services_create_endpoint", name, bucket, scope, tuple(sorted(functions)))
        self.endpoints[name] = EndpointState(bucket, scope, dict(functions))

    def app_services_link_collection(self, name: str, scope: str, collection: str, function: str) -> None:
        self._write("app_services_link_collection", name, scope, collection)
        self.endpoints[name].functions[collection] = function

    def app_services_set_sync_function(self, name: str, scope: str, collection: str, function: str) -> None:
        self._write("app_services_set_sync_function", name, scope, collection)
        self.endpoints[name].functions[collection] = function

    def app_services_get_users(self, name: str) -> dict[str, Channels]:
        return copy.deepcopy(self.users.get(name, {}))

    def app_services_put_user(self, name: str, scope: str, user: str, channels: Channels,
                              password: str | None) -> None:
        self._write("app_services_put_user", name, user)
        self.users.setdefault(name, {})[user] = copy.deepcopy(channels)
        if password is not None:
            self.passwords[user] = password

    def app_services_session(self, user: str, password: str, scope: str, collections: list[str]) -> Channels:
        for users in self.users.values():
            if user in users and self.passwords.get(user) == password:
                return copy.deepcopy(users[user])
        raise PermissionError(f"App Services refused the session for {user}")
