import io
import socket

import pytest

from siab_capella.__main__ import main
from siab_capella.config import Config
from siab_capella.gateway import FakeCapella

PASSWORDS = {"BOX_APP_PASSWORD": "test-box-password", "HQ_APP_PASSWORD": "test-hq-password"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Unit tests never reach a live service: any socket connect fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("a unit test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def fake():
    return FakeCapella()


@pytest.fixture
def cli(fake):
    """Run the CLI against the fake; returns (exit code, output)."""

    def run(*argv, env=None, gateway=fake):
        out = io.StringIO()
        code = main(list(argv), gateway=gateway, config=Config(dict(PASSWORDS if env is None else env)), out=out)
        return code, out.getvalue()

    return run
