from __future__ import annotations

import asyncio
import inspect
import ipaddress
import socket
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import psutil

from app.schemas.camera_discovery import (
    OnvifDiscoveryCandidate,
    OnvifDiscoveryResponse,
    RtspDiscoveryCandidate,
    RtspDiscoveryResponse,
)
from app.services.onvif_client import OnvifError, validate_service_url


WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
WSD = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
DN = "http://www.onvif.org/ver10/network/wsdl"
MULTICAST_TARGET = ("239.255.255.250", 3702)
MAX_DATAGRAM_BYTES = 64 * 1024
MAX_ONVIF_CANDIDATES = 256
MAX_RTSP_TARGETS = 254


class CameraDiscoveryError(RuntimeError):
    pass


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_text(element: ET.Element, local_name: str) -> str | None:
    for node in element.iter():
        if _local_name(node.tag) == local_name and node.text:
            value = node.text.strip()
            if value:
                return value
    return None


def build_ws_discovery_probe(message_id: str | None = None) -> bytes:
    resolved_id = message_id or f"urn:uuid:{uuid.uuid4()}"
    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
        f'xmlns:w="{WSA}" xmlns:d="{WSD}" xmlns:dn="{DN}">'
        "<e:Header>"
        f"<w:MessageID>{resolved_id}</w:MessageID>"
        f"<w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>"
        f'<w:Action>{WSD}/Probe</w:Action>'
        "</e:Header>"
        "<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>"
        "</e:Envelope>"
    )
    return payload.encode("utf-8")


def _safe_xaddrs(raw_values: list[str]) -> list[str]:
    values: list[str] = []
    for raw in raw_values:
        candidate = raw.strip()
        if not candidate:
            continue
        try:
            validated = validate_service_url(candidate)
            parsed = urlsplit(validated)
            _ = parsed.port
        except (OnvifError, ValueError):
            continue
        if validated not in values:
            values.append(validated)
    return values


def _preferred_xaddr(xaddrs: list[str]) -> str | None:
    for value in xaddrs:
        hostname = urlsplit(value).hostname
        if not hostname:
            continue
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            continue
        return value
    return xaddrs[0] if xaddrs else None


def _apply_preferred_service(candidate: OnvifDiscoveryCandidate) -> None:
    selected = _preferred_xaddr(candidate.xaddrs)
    if selected is None:
        candidate.device_service_url = None
        candidate.host = None
        candidate.port = None
        candidate.selectable = False
        candidate.unavailable_reason = (
            "设备已响应 WS-Discovery，但未提供可用的 ONVIF Device Service 地址"
        )
        return

    parsed = urlsplit(selected)
    candidate.device_service_url = selected
    candidate.host = parsed.hostname
    candidate.port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    candidate.selectable = True
    candidate.unavailable_reason = None


def parse_probe_matches(
    xml: str | bytes,
    *,
    source_host: str | None = None,
) -> tuple[list[OnvifDiscoveryCandidate], list[str]]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], ["malformed WS-Discovery response ignored"]

    candidates: list[OnvifDiscoveryCandidate] = []
    for match in root.iter():
        if _local_name(match.tag) != "ProbeMatch":
            continue

        endpoint_reference = None
        for node in match.iter():
            if _local_name(node.tag) == "EndpointReference":
                endpoint_reference = _first_text(node, "Address")
                break

        raw_xaddrs: list[str] = []
        raw_scopes: list[str] = []
        for node in match.iter():
            name = _local_name(node.tag)
            if name == "XAddrs" and node.text:
                raw_xaddrs.extend(node.text.split())
            elif name == "Scopes" and node.text:
                raw_scopes.extend(node.text.split())

        candidate = OnvifDiscoveryCandidate(
            endpoint_reference=endpoint_reference,
            xaddrs=_safe_xaddrs(raw_xaddrs),
            scopes=list(dict.fromkeys(scope.strip() for scope in raw_scopes if scope.strip())),
            source_host=source_host,
        )
        _apply_preferred_service(candidate)
        candidates.append(candidate)
        if len(candidates) >= MAX_ONVIF_CANDIDATES:
            break

    return candidates, []


def _candidate_key(candidate: OnvifDiscoveryCandidate) -> str:
    if candidate.endpoint_reference:
        return f"epr:{candidate.endpoint_reference.strip().lower()}"
    if candidate.device_service_url:
        return f"url:{candidate.device_service_url.strip().lower()}"
    scopes = "|".join(sorted(candidate.scopes))
    return f"source:{candidate.source_host or ''}|scopes:{scopes}"


def merge_onvif_candidates(
    candidates: list[OnvifDiscoveryCandidate],
) -> list[OnvifDiscoveryCandidate]:
    merged: dict[str, OnvifDiscoveryCandidate] = {}
    order: list[str] = []

    for item in candidates:
        key = _candidate_key(item)
        existing = merged.get(key)
        if existing is None:
            existing = item.model_copy(deep=True)
            merged[key] = existing
            order.append(key)
        else:
            for value in item.xaddrs:
                if value not in existing.xaddrs:
                    existing.xaddrs.append(value)
            for value in item.scopes:
                if value not in existing.scopes:
                    existing.scopes.append(value)
            if not existing.endpoint_reference and item.endpoint_reference:
                existing.endpoint_reference = item.endpoint_reference
            if not existing.source_host and item.source_host:
                existing.source_host = item.source_host

        _apply_preferred_service(existing)
        if len(order) >= MAX_ONVIF_CANDIDATES:
            break

    return [merged[key] for key in order[:MAX_ONVIF_CANDIDATES]]


def scan_onvif(timeout_seconds: float = 3.0) -> OnvifDiscoveryResponse:
    timeout = max(0.1, min(float(timeout_seconds), 3.0))
    started = time.monotonic()
    deadline = started + timeout
    collected: list[OnvifDiscoveryCandidate] = []
    warnings: list[str] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.bind(("", 0))
        sock.sendto(build_ws_discovery_probe(), MULTICAST_TARGET)

        while len(collected) < MAX_ONVIF_CANDIDATES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(min(0.25, remaining))
            try:
                payload, address = sock.recvfrom(MAX_DATAGRAM_BYTES)
            except socket.timeout:
                continue
            except OSError as exc:
                warnings.append(f"WS-Discovery receive stopped: {exc.__class__.__name__}")
                break

            if len(payload) >= MAX_DATAGRAM_BYTES:
                warnings.append("oversized WS-Discovery response ignored")
                continue
            parsed, packet_warnings = parse_probe_matches(
                payload,
                source_host=str(address[0]) if address else None,
            )
            collected.extend(parsed)
            warnings.extend(packet_warnings)
    finally:
        sock.close()

    devices = merge_onvif_candidates(collected)
    return OnvifDiscoveryResponse(
        devices=devices,
        scan_duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        warnings=warnings[:32],
    )


def parse_default_route_interface(route_text: str) -> str | None:
    choices: list[tuple[int, str]] = []
    for line in route_text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8 or fields[1] != "00000000":
            continue
        try:
            flags = int(fields[3], 16)
            metric = int(fields[6])
        except ValueError:
            continue
        if flags & 0x1:
            choices.append((metric, fields[0]))
    return min(choices)[1] if choices else None


def rtsp_scan_network(interface_ip: ipaddress.IPv4Address) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(f"{interface_ip}/24", strict=False)


def default_route_ipv4_network(
    route_path: str | Path = "/proc/net/route",
) -> tuple[ipaddress.IPv4Network, ipaddress.IPv4Address]:
    try:
        route_text = Path(route_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CameraDiscoveryError("无法读取默认路由") from exc

    interface = parse_default_route_interface(route_text)
    if not interface:
        raise CameraDiscoveryError("未找到可用于局域网扫描的 IPv4 默认路由")

    for address in psutil.net_if_addrs().get(interface, []):
        if address.family != socket.AF_INET:
            continue
        try:
            ip = ipaddress.ip_address(address.address)
        except ValueError:
            continue
        if not isinstance(ip, ipaddress.IPv4Address) or ip.is_loopback:
            continue
        if not (ip.is_private or ip.is_link_local):
            continue
        return rtsp_scan_network(ip), ip

    raise CameraDiscoveryError("默认路由接口没有可用于局域网扫描的私有 IPv4 地址")


async def _close_writer(writer: object) -> None:
    close = getattr(writer, "close", None)
    if callable(close):
        close()
    wait_closed = getattr(writer, "wait_closed", None)
    if callable(wait_closed):
        result = wait_closed()
        if inspect.isawaitable(result):
            await result


async def scan_rtsp_port_554(
    *,
    network: ipaddress.IPv4Network | None = None,
    self_ip: ipaddress.IPv4Address | None = None,
    open_connection: Callable[[str, int], Awaitable[tuple[object, object]]] = asyncio.open_connection,
    connect_timeout: float = 0.3,
    overall_timeout: float = 3.0,
    concurrency: int = 64,
) -> RtspDiscoveryResponse:
    if network is None or self_ip is None:
        network, self_ip = default_route_ipv4_network()

    started = time.monotonic()
    semaphore = asyncio.Semaphore(max(1, min(int(concurrency), 64)))
    per_host_timeout = max(0.01, min(float(connect_timeout), 0.3))
    hard_timeout = max(0.1, min(float(overall_timeout), 3.0))
    targets = [
        host
        for host in network.hosts()
        if host != self_ip
    ][:MAX_RTSP_TARGETS]

    async def probe(host: ipaddress.IPv4Address) -> RtspDiscoveryCandidate | None:
        async with semaphore:
            writer: object | None = None
            try:
                _reader, writer = await asyncio.wait_for(
                    open_connection(str(host), 554),
                    timeout=per_host_timeout,
                )
                return RtspDiscoveryCandidate(host=str(host))
            except (OSError, asyncio.TimeoutError):
                return None
            finally:
                if writer is not None:
                    await _close_writer(writer)

    tasks = [asyncio.create_task(probe(host)) for host in targets]
    done, pending = await asyncio.wait(tasks, timeout=hard_timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    devices = [
        result
        for task in done
        if not task.cancelled()
        and not isinstance((result := task.result()), BaseException)
        and result is not None
    ]
    devices.sort(key=lambda item: ipaddress.ip_address(item.host))

    return RtspDiscoveryResponse(
        network=str(network),
        devices=devices,
        scan_duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        warnings=[],
    )
