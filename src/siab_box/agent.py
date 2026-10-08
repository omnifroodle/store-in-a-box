"""Wire the agent together: proxy on loopback, status API on every interface, the probe and the Edge Server poll."""

from __future__ import annotations

import asyncio
import socket
import ssl

import httpx

from . import status
from .clock import Clock, SystemClock
from .edge import EdgeMonitor, file_credentials
from .proxy import ByteCounter, CountingProxy
from .settings import Settings
from .uplink import Uplink, UplinkProbe


def lan_ip() -> str:
    """The address of the interface the default route uses (no packet is sent), or loopback when there is none."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: never routed, only used to pick an interface
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _edge_verify(settings: Settings) -> ssl.SSLContext | bool:
    if not settings.edge_tls:
        return True
    if not settings.cert_path.exists():
        return False
    ctx = ssl.create_default_context(cafile=str(settings.cert_path))
    ctx.check_hostname = False  # the self-signed cert names the LAN address; the agent calls 127.0.0.1
    return ctx


def build_box(settings: Settings, edge_client: httpx.AsyncClient, host_ip: str, clock: Clock) -> status.Box:
    counter = ByteCounter(clock)
    uplink = Uplink(clock, settings.target.host)
    proxy = CountingProxy(settings.target, counter, uplink)
    edge = EdgeMonitor(edge_client, file_credentials(settings.agent_credentials_path), clock,
                       settings.proxy_port, settings.target.host)
    scheme = "wss" if settings.edge_tls else "ws"
    return status.Box(
        box_id=settings.box_id, trip=settings.trip, edge_url=f"{scheme}://{host_ip}:{settings.edge_port}/retail",
        edge_tls=settings.edge_tls, cert_path=settings.cert_path, device_passwords=settings.device_passwords,
        counter=counter, uplink=uplink, proxy=proxy, edge=edge)


async def run(settings: Settings, host_ip: str | None = None, edge_url: str | None = None,
              clock: Clock | None = None) -> None:
    clock = clock or SystemClock()
    host_ip = host_ip or lan_ip()
    local = edge_url or f"{'https' if settings.edge_tls else 'http'}://127.0.0.1:{settings.edge_port}"
    async with httpx.AsyncClient(base_url=local, verify=_edge_verify(settings), timeout=3.0) as client:
        box = build_box(settings, client, host_ip, clock)
        proxy_server = await box.proxy.serve("127.0.0.1", settings.proxy_port)
        status_server = await status.serve(box, "0.0.0.0", settings.box_port)
        print(f"siab-box: status on http://{host_ip}:{settings.box_port}/ ; proxy on 127.0.0.1:{settings.proxy_port}"
              f" -> {settings.target.host}:{settings.target.port} ; Edge Server at {local}", flush=True)
        probe = UplinkProbe(box.uplink, settings.target.port, clock)
        async with proxy_server, status_server:
            await asyncio.gather(probe.run(), box.edge.run())
