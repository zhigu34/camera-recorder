import asyncio
import importlib
import ipaddress

import pytest


PROBE_MATCH_WITHOUT_XADDR = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope
  xmlns:e="http://www.w3.org/2003/05/soap-envelope"
  xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <e:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <w:EndpointReference><w:Address>urn:uuid:camera-1</w:Address></w:EndpointReference>
        <d:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/name/front</d:Scopes>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </e:Body>
</e:Envelope>
"""

PROBE_MATCH_WITH_CREDENTIAL_XADDR = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope
  xmlns:e="http://www.w3.org/2003/05/soap-envelope"
  xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <e:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <w:EndpointReference><w:Address>urn:uuid:camera-2</w:Address></w:EndpointReference>
        <d:XAddrs>http://admin:secret@192.168.1.21/onvif/device_service</d:XAddrs>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </e:Body>
</e:Envelope>
"""

PROBE_MATCH_A = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope
  xmlns:e="http://www.w3.org/2003/05/soap-envelope"
  xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <e:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <w:EndpointReference><w:Address>urn:uuid:camera-3</w:Address></w:EndpointReference>
        <d:Scopes>onvif://www.onvif.org/name/front-door</d:Scopes>
        <d:XAddrs>http://camera.local/onvif/device_service http://192.168.1.50/onvif/device_service</d:XAddrs>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </e:Body>
</e:Envelope>
"""

PROBE_MATCH_B = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope
  xmlns:e="http://www.w3.org/2003/05/soap-envelope"
  xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <e:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <w:EndpointReference><w:Address>urn:uuid:camera-3</w:Address></w:EndpointReference>
        <d:Scopes>onvif://www.onvif.org/type/video_encoder</d:Scopes>
        <d:XAddrs>http://192.168.1.50/onvif/device_service</d:XAddrs>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </e:Body>
</e:Envelope>
"""


def discovery():
    try:
        return importlib.import_module("app.services.camera_discovery")
    except ModuleNotFoundError:
        pytest.fail("camera discovery service is not implemented yet")


def test_ws_discovery_probe_targets_network_video_transmitter() -> None:
    module = discovery()
    payload = module.build_ws_discovery_probe("urn:uuid:test-message")

    assert b"urn:uuid:test-message" in payload
    assert b"NetworkVideoTransmitter" in payload
    assert b"Probe" in payload


def test_probe_match_without_xaddr_remains_visible_but_unselectable() -> None:
    module = discovery()
    candidates, warnings = module.parse_probe_matches(
        PROBE_MATCH_WITHOUT_XADDR,
        source_host="192.168.1.20",
    )

    assert warnings == []
    assert len(candidates) == 1
    assert candidates[0].endpoint_reference == "urn:uuid:camera-1"
    assert candidates[0].host is None
    assert candidates[0].device_service_url is None
    assert candidates[0].selectable is False
    assert candidates[0].unavailable_reason


def test_credential_bearing_xaddr_is_rejected_without_hiding_candidate() -> None:
    module = discovery()
    candidates, warnings = module.parse_probe_matches(
        PROBE_MATCH_WITH_CREDENTIAL_XADDR,
        source_host="192.168.1.21",
    )

    assert warnings == []
    assert len(candidates) == 1
    assert candidates[0].xaddrs == []
    assert candidates[0].selectable is False


def test_duplicate_epr_merges_xaddrs_scopes_and_prefers_ip_xaddr() -> None:
    module = discovery()
    first, _ = module.parse_probe_matches(PROBE_MATCH_A, source_host="192.168.1.50")
    second, _ = module.parse_probe_matches(PROBE_MATCH_B, source_host="192.168.1.50")

    merged = module.merge_onvif_candidates([*first, *second])

    assert len(merged) == 1
    candidate = merged[0]
    assert candidate.xaddrs == [
        "http://camera.local/onvif/device_service",
        "http://192.168.1.50/onvif/device_service",
    ]
    assert candidate.scopes == [
        "onvif://www.onvif.org/name/front-door",
        "onvif://www.onvif.org/type/video_encoder",
    ]
    assert candidate.device_service_url == "http://192.168.1.50/onvif/device_service"
    assert candidate.host == "192.168.1.50"
    assert candidate.port == 80
    assert candidate.selectable is True


def test_malformed_probe_match_is_isolated_as_warning() -> None:
    module = discovery()
    candidates, warnings = module.parse_probe_matches("<broken>", source_host="192.168.1.9")

    assert candidates == []
    assert len(warnings) == 1
    assert "malformed" in warnings[0].lower()


def test_default_route_parser_selects_zero_destination_route() -> None:
    module = discovery()
    route_text = """Iface	Destination	Gateway	Flags	RefCnt	Use	Metric	Mask	MTU	Window	IRTT
eth0	00000000	0101A8C0	0003	0	0	100	00000000	0	0	0
eth1	0001A8C0	00000000	0001	0	0	50	00FFFFFF	0	0	0
"""

    assert module.parse_default_route_interface(route_text) == "eth0"


def test_rtsp_scan_network_is_default_route_ipv4_slash_24() -> None:
    module = discovery()

    network = module.rtsp_scan_network(ipaddress.ip_address("192.168.12.73"))

    assert network == ipaddress.ip_network("192.168.12.0/24")


class FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, value: bytes) -> None:
        self.writes.append(value)

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_rtsp_scan_connects_only_to_554_and_writes_no_application_data() -> None:
    module = discovery()
    calls: list[tuple[str, int]] = []
    writers: list[FakeWriter] = []

    async def fake_open_connection(host: str, port: int):
        calls.append((host, port))
        if host not in {"192.168.7.20", "192.168.7.40"}:
            raise OSError("closed")
        writer = FakeWriter()
        writers.append(writer)
        return asyncio.StreamReader(), writer

    response = await module.scan_rtsp_port_554(
        network=ipaddress.ip_network("192.168.7.0/24"),
        self_ip=ipaddress.ip_address("192.168.7.10"),
        open_connection=fake_open_connection,
        connect_timeout=0.05,
        overall_timeout=1.0,
        concurrency=64,
    )

    assert response.network == "192.168.7.0/24"
    assert [(item.host, item.port) for item in response.devices] == [
        ("192.168.7.20", 554),
        ("192.168.7.40", 554),
    ]
    assert all(port == 554 for _, port in calls)
    assert ("192.168.7.10", 554) not in calls
    assert all(writer.writes == [] for writer in writers)
    assert all(writer.closed for writer in writers)
