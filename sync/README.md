# Sync functions

One App Services sync function (access control function) per linked collection of the App Endpoint `store`:

| File | Collection | Writer | Routes to |
|---|---|---|---|
| `functions/store.product.js` | `product` | `hq` | `catalog:<region>` for each of `regions` |
| `functions/store.trip.js` | `trip` | `hq` | `trip:<trip_id>`, `box:<box>` |
| `functions/store.allocation.js` | `allocation` | its `box`, or `hq` | `trip:<trip>`; later only `status`, `closed_at` change |
| `functions/store.transaction.js` | `transaction` | its `box`, or `hq` (`box` may be null) | `trip:<trip>`; never updated |
| `functions/store.exception.js` | `exception` | its `box` (status `open`), or `hq` | `trip:<trip>`; only `hq` updates, only `status`, `resolution` |

`inventory` is never linked: store on-hand never reaches a venue. Deletes are `hq` only and route the tombstone to
the old document's channels. The rules, the order the checks run in and the error words are in
`contracts/fixtures/README.md` ("`sync/<case>.json`").

Each file is one `function (doc, oldDoc, meta) { ... }` expression, pasted as is into App Services (or set by
`siab-capella app-services apply` from `app-endpoint.json`). They are written in ES5 (`var`, `function`, no arrow
functions or template strings), which the App Services JavaScript engine accepts. The writer check uses
`requireUser` inside a `try`, so the admin context (an import of a document written through the SDK, such as
`reset-trip`'s deletes) passes as `hq` does.

## Tests

```
node --test sync/tests/
```

`tests/harness.mjs` is a fake of the App Services runtime (`channel`, `access`, `requireUser`, `requireAccess`,
`requireRole`, `requireAdmin`, with Sync Gateway's semantics: a user holding `*` has every channel, and the admin
context passes every `require*`). `tests/fixtures.test.mjs` runs every case in `contracts/fixtures/sync/`;
`tests/rules.test.mjs` covers what the fixtures leave open (admin context, tombstones, field order, ES5 only).
The harness is a fake: the behaviour on the real runtime is checked live (see `docs/capella-setup.md`).

## `app-endpoint.json`

What `app-services apply` works from: the endpoint name, bucket and scope, each linked collection's function file
(relative to `sync/`), and the app users with their channels, which apply to every linked collection. Passwords are
not in it: each user names the `.env` variable that holds its password (`password_env`) and its name
(`user_env`). The users and channels equal `contracts/fixtures/seed/custodians.json` (a test checks it).
