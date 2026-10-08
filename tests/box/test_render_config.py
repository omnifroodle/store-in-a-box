"""render-config: the Edge Server config and users file from the environment, with a fake bcrypt."""

from __future__ import annotations

import json
import re
import stat

import jsonschema
import pytest

from siab_box import __main__ as cli
from siab_box import render_config
from siab_box.render_config import AGENT_USER, RenderError

COLLECTIONS = ["store.product", "store.trip", "store.allocation", "store.transaction", "store.exception"]
CHANNELS = ["trip:trip-2026-10-18-riverfest", "catalog:va-central", "box:box-07"]

# The parts of the Edge Server 1.1 configuration schema this config uses, written from
# https://packages.couchbase.com/couchbase-edge-server/config_schema.json (additionalProperties false throughout, as
# there), so a misspelt key fails here rather than on the box.
STR = {"type": "string"}
EDGE_CONFIG = {
    "type": "object", "required": ["databases"], "additionalProperties": False,
    "properties": {
        "$schema": STR, "interface": STR, "users": STR, "enable_anonymous_users": {"type": "boolean"},
        "https": {"type": "object", "required": ["tls_cert_path", "tls_key_path"], "additionalProperties": False,
                  "properties": {"tls_cert_path": STR, "tls_key_path": STR, "client_cert_path": STR}},
        "databases": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["path"], "additionalProperties": False,
            "properties": {"path": {"type": "string", "pattern": r"\.cblite2$"}, "create": {"type": "boolean"},
                           "enable_client_sync": {"enum": ["push", "pull", "bidirectional", True]},
                           "enable_client_writes": {"type": "boolean"},
                           "collections": {"type": "array", "items": {"pattern": "^[-A-Za-z0-9_%.]+$"}}}}},
        "logging": {"type": "object", "additionalProperties": False, "properties": {"console": {"type": "boolean"}}},
        "replications": {"type": "array", "items": {
            "type": "object", "required": ["source", "target"], "additionalProperties": False,
            "properties": {
                "source": STR, "target": STR, "bidirectional": {"type": "boolean"}, "continuous": {"type": "boolean"},
                "collections": {"type": "object", "additionalProperties": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"channels": {"type": "array", "items": STR, "uniqueItems": True}}}},
                "auth": {"type": "object", "additionalProperties": False,
                         "properties": {"user": STR, "password": STR}}}}},
    },
}
USERS = {"type": "object", "additionalProperties": {
    "type": "object", "required": ["password"], "additionalProperties": False,
    "properties": {"password": {"type": "string", "pattern": r"^\$2[a-z]\$\d\d\$[A-Za-z0-9/.]+$"},
                   "roles": {"type": "array", "items": STR}}}}


def fake_bcrypt(user, password):
    return "$2y$10$" + re.sub(r"[^A-Za-z0-9]", ".", f"{user}{password}").ljust(53, "x")


def _template():
    return render_config.TEMPLATE.read_text(encoding="utf-8")


def test_render_config_refuses_missing_env(kit, tmp_path):
    env = dict(kit.ENV)
    del env["BOX_APP_PASSWORD"]
    env["EDGE_PHONE_1_PASSWORD"] = ""
    with pytest.raises(RenderError) as err:
        render_config.render(_template(), env, tmp_path)
    assert "BOX_APP_PASSWORD" in str(err.value) and "EDGE_PHONE_1_PASSWORD" in str(err.value)
    with pytest.raises(RenderError):
        render_config.write(tmp_path / "config.json", env, fake_bcrypt)
    assert list(tmp_path.iterdir()) == []  # nothing half-written


def test_refuses_a_placeholder_nobody_sets(kit, tmp_path):
    with pytest.raises(RenderError, match="SIAB_SOMETHING_NEW"):
        render_config.render('{"x": "${SIAB_SOMETHING_NEW}"}', kit.ENV, tmp_path)


def test_render_names_five_collections_and_the_replication(kit, tmp_path):
    config = render_config.render(_template(), kit.ENV, tmp_path)
    jsonschema.validate(config, EDGE_CONFIG)
    assert config["interface"] == "0.0.0.0:59840"
    assert config["enable_anonymous_users"] is False
    assert config["users"] == f"{tmp_path.resolve()}/users.json"
    db = config["databases"]["retail"]
    assert db["collections"] == COLLECTIONS and db["path"].endswith("/retail.cblite2")
    assert db["enable_client_sync"] == "bidirectional"
    [rep] = config["replications"]
    assert rep["source"] == "retail" and rep["target"] == "ws://127.0.0.1:8790/store"
    assert rep["bidirectional"] is True and rep["continuous"] is True
    assert list(rep["collections"]) == COLLECTIONS
    assert all(c["channels"] == CHANNELS for c in rep["collections"].values())
    assert rep["auth"] == {"user": "box-07", "password": "box-secret"}
    assert "https" not in config


def test_values_are_json_escaped_and_ports_and_tls_apply(kit, tmp_path):
    env = {**kit.ENV, "BOX_APP_PASSWORD": 'qu"o\\te', "EDGE_PORT": "60000", "SIAB_PROXY_PORT": "8899",
           "EDGE_TLS": "on", "SIAB_BOX_ID": "box-09"}
    config = render_config.render(_template(), env, tmp_path)
    jsonschema.validate(config, EDGE_CONFIG)
    assert config["replications"][0]["auth"]["password"] == 'qu"o\\te'
    assert config["interface"] == "0.0.0.0:60000"
    assert config["replications"][0]["target"] == "ws://127.0.0.1:8899/store"
    assert config["replications"][0]["collections"]["store.trip"]["channels"][-1] == "box:box-09"
    assert config["https"] == {"tls_cert_path": f"{tmp_path.resolve()}/cert.pem",
                               "tls_key_path": f"{tmp_path.resolve()}/key.pem"}


def test_bad_values_refused(kit, tmp_path):
    for name, value in (("EDGE_TLS", "maybe"), ("APP_SERVICES_PUBLIC_URL", "https://x.test/store"),
                        ("APP_SERVICES_PUBLIC_URL", "wss://x.test/")):
        with pytest.raises(RenderError):
            render_config.render(_template(), {**kit.ENV, name: value}, tmp_path)


def test_write_config_users_and_agent_credentials(kit, tmp_path):
    out = tmp_path / "edge" / "config.json"
    paths = render_config.write(out, kit.ENV, fake_bcrypt)
    assert [p.name for p in paths] == ["config.json", "users.json", "agent.json"]
    for path in paths:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    users = json.loads((out.parent / "users.json").read_text())
    jsonschema.validate(users, USERS)
    assert list(users) == ["tablet-a", "tablet-b", "phone-1", AGENT_USER]
    assert users[AGENT_USER]["roles"] == ["replicate"] and "roles" not in users["tablet-a"]
    agent = json.loads((out.parent / "agent.json").read_text())
    assert agent["user"] == AGENT_USER and len(agent["password"]) >= 24
    assert json.loads(out.read_text())["users"] == str((out.parent / "users.json").resolve())


def test_cli_render_config(kit, tmp_path, monkeypatch, capsys):
    for name, value in kit.ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(render_config, "htpasswd_hash", fake_bcrypt)
    assert cli.main(["render-config", "--out", str(tmp_path / "x.json")]) == 0
    assert json.loads((tmp_path / "x.json").read_text())["databases"]["retail"]["collections"] == COLLECTIONS
    monkeypatch.delenv("SIAB_TRIP")
    assert cli.main(["render-config", "--out", str(tmp_path / "y.json")]) == 2
    assert "SIAB_TRIP" in capsys.readouterr().err
    assert not (tmp_path / "y.json").exists()
