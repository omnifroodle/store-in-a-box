# Port: Capella gateway

Owner: WS2 (`src/siab_capella/gateway.py`). Users: the `siab-capella` CLI (WS2) and the HQ screen's reads (WS5).

## `CapellaGateway`

A `typing.Protocol`. Implementations: `siab_capella.live.LiveCapella` (Couchbase Python SDK for documents, queries
and indexes; Capella Management API v4 for the bucket, scopes, collections and App Services; the App Services public
REST API for sessions) and `siab_capella.gateway.FakeCapella` (in memory, for unit tests).

| Operation | Meaning |
|---|---|
| `ensure_bucket(bucket, *, apply)` | `apply=False`: True if missing. `apply=True`: create if missing; True if it did. |
| `ensure_scope(bucket, scope, *, apply)` | Same contract. A missing bucket means a missing scope. |
| `ensure_collection(ks, *, apply)` | Same contract; `ks` is a `Keyspace(bucket, scope, collection)`. |
| `ensure_index(name, ks, fields, *, apply)` | Same contract, by index name (a changed field list is not detected). |
| `get(ks, id) -> dict \| None` | One document, or None. |
| `upsert(ks, id, doc)` | Write a document (the cluster database credential, not an App Services user). |
| `delete(ks, id)` | Remove a document; a missing one is not an error. |
| `query(statement, params) -> list` | SQL++ with named parameters (`$trip`). Use `Keyspace.sqlpp()` for the keyspace: `transaction` is a reserved word. |
| `app_services_get_endpoint(name) -> EndpointState \| None` | `bucket`, `scope`, and `functions` (linked collection -> sync function source). |
| `app_services_create_endpoint(name, bucket, scope, functions)` | Create the endpoint linking those collections. |
| `app_services_link_collection(name, scope, collection, function)` | Link one more collection. |
| `app_services_set_sync_function(name, scope, collection, function)` | Replace one collection's sync function. |
| `app_services_get_users(name) -> {user: {collection: [channels]}}` | The endpoint's app users and their grants. |
| `app_services_put_user(name, scope, user, channels, password)` | Create or update a user; `password=None` keeps it. |
| `app_services_session(user, password, scope, collections) -> {collection: [channels]}` | Log in on the public endpoint as `user`; raises `PermissionError` if refused. May include the public channel `!`. |

Any `app_services_*` write may raise `ManualStepRequired(steps)`: the Management API does not reach that step, and
`steps` are the instructions for the Capella UI. The CLI prints them and exits 2.

`FakeCapella` records every write in `calls` (tuples, e.g. `("upsert", Keyspace(...), "product::X")`), raises
`ManualStepRequired` for the method names in `manual`, and its `query` understands one shape
(`SELECT RAW META(d).id FROM <ks> AS d WHERE d.`<field>` = $<param>`); set `query_handler(statement, params)` for
others.

## Environment variables

The names are the contract (values live in `.env`, never committed; `.env.example` lists them):
`CAPELLA_CONN_STRING`, `CAPELLA_DB_USERNAME`, `CAPELLA_DB_PASSWORD`, `CAPELLA_API_KEY`, `CAPELLA_API_BASE`,
`CAPELLA_ORG_ID`, `CAPELLA_PROJECT_ID`, `CAPELLA_CLUSTER_ID`, `CAPELLA_APP_SERVICE_ID`, `APP_SERVICES_PUBLIC_URL`,
`APP_SERVICES_ADMIN_URL`, `SIAB_TRIP`, `SIAB_REGION`, `BOX_APP_USER`, `BOX_APP_PASSWORD`, `HQ_APP_USER`,
`HQ_APP_PASSWORD`. Meanings: `docs/capella-setup.md`. WS3 reads `APP_SERVICES_PUBLIC_URL`, `BOX_APP_USER` and
`BOX_APP_PASSWORD`; WS5 reads the `CAPELLA_DB_*` credential and `HQ_APP_*`.

## Names

Bucket `retail`; scopes `store`, `agents`, `ref`; Phase 0 collections in `store`: `product`, `inventory`, `trip`,
`allocation`, `transaction`, `exception`. App Endpoint `store` over scope `store`, linking every collection but
`inventory`. Channels and users: `contracts/fixtures/README.md` and `sync/app-endpoint.json`.
