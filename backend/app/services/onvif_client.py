from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import httpx

SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
TDS = "http://www.onvif.org/ver10/device/wsdl"
TRT = "http://www.onvif.org/ver10/media/wsdl"
TEV = "http://www.onvif.org/ver10/events/wsdl"
TT = "http://www.onvif.org/ver10/schema"
WSNT = "http://docs.oasis-open.org/wsn/b-2"
WSA = "http://www.w3.org/2005/08/addressing"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
PASSWORD_DIGEST = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
)
NONCE_BASE64 = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-soap-message-security-1.0#Base64Binary"
)


class OnvifError(RuntimeError):
    pass


@dataclass(frozen=True)
class OnvifSubscription:
    reference_url: str
    current_time: datetime | None
    termination_time: datetime | None


@dataclass(frozen=True)
class OnvifNotification:
    topic: str
    occurred_at: datetime
    event_type: str
    property_operation: str | None
    source: dict[str, str]
    data: dict[str, str]
    active: bool | None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_onvif_event_type(topic: str, data: dict[str, str] | None = None) -> str:
    haystack = " ".join([topic, *list((data or {}).keys())]).lower()
    if any(token in haystack for token in ("person", "human", "people")):
        return "person"
    if any(token in haystack for token in ("vehicle", "automobile", "/car", "cardetected")):
        return "vehicle"
    if any(
        token in haystack
        for token in ("intrusion", "linecross", "line_cross", "crossline", "regionentrance")
    ):
        return "intrusion"
    if "tamper" in haystack:
        return "tamper"
    if any(token in haystack for token in ("digitalinput", "digital_input", "relayinput")):
        return "digital_input"
    if any(token in haystack for token in ("motion", "cellmotiondetector", "ismotion")):
        return "motion"
    return "unknown"


def event_types_for_topics(topics: list[str]) -> list[str]:
    result: list[str] = []
    for topic in topics:
        event_type = normalize_onvif_event_type(topic)
        if event_type != "unknown" and event_type not in result:
            result.append(event_type)
    return result


def parse_event_topics(xml: str | bytes) -> list[str]:
    root = _xml_root(xml)
    topic_set = next((node for node in root.iter() if _local_name(node.tag) == "TopicSet"), None)
    if topic_set is None:
        return []

    metadata_nodes = {
        "MessageDescription",
        "Source",
        "Data",
        "Key",
        "SimpleItemDescription",
        "ElementItemDescription",
    }
    topics: list[str] = []

    def visit(node: ET.Element, path: list[str]) -> None:
        for child in list(node):
            name = _local_name(child.tag)
            if name in metadata_nodes:
                continue
            child_path = [*path, name]
            topic_children = [
                item for item in list(child) if _local_name(item.tag) not in metadata_nodes
            ]
            has_description = any(
                _local_name(item.tag) == "MessageDescription" for item in child.iter()
            )
            if has_description and not topic_children:
                topics.append("/".join(child_path))
            else:
                visit(child, child_path)

    visit(topic_set, [])
    return list(dict.fromkeys(topics))


def parse_subscription(xml: str | bytes) -> OnvifSubscription:
    root = _xml_root(xml)
    reference_url = _text_in(root, "Address")
    if not reference_url:
        raise OnvifError("ONVIF subscription response has no reference address")
    return OnvifSubscription(
        reference_url=validate_service_url(reference_url),
        current_time=_parse_datetime(_text_in(root, "CurrentTime")),
        termination_time=_parse_datetime(_text_in(root, "TerminationTime")),
    )


def parse_renewal_time(xml: str | bytes) -> datetime | None:
    return _parse_datetime(_text_in(_xml_root(xml), "TerminationTime"))


def _simple_items(message: ET.Element, section: str) -> dict[str, str]:
    container = next(
        (node for node in message.iter() if _local_name(node.tag) == section),
        None,
    )
    if container is None:
        return {}
    values: dict[str, str] = {}
    for item in container.iter():
        if _local_name(item.tag) != "SimpleItem":
            continue
        name = (item.attrib.get("Name") or "").strip()
        if name:
            values[name] = str(item.attrib.get("Value") or "")
    return values


def _notification_active(data: dict[str, str]) -> bool | None:
    candidates = [
        value
        for key, value in data.items()
        if any(token in key.lower() for token in ("state", "motion", "active", "alarm", "detected"))
    ]
    if not candidates:
        return None
    value = candidates[0].strip().lower()
    if value in {"true", "1", "on", "active", "yes"}:
        return True
    if value in {"false", "0", "off", "inactive", "no"}:
        return False
    return None


def parse_pull_messages(xml: str | bytes) -> list[OnvifNotification]:
    root = _xml_root(xml)
    notifications: list[OnvifNotification] = []
    for node in root.iter():
        if _local_name(node.tag) != "NotificationMessage":
            continue
        topic = _text_in(node, "Topic") or ""
        message = next(
            (
                item
                for item in node.iter()
                if _local_name(item.tag) == "Message" and "UtcTime" in item.attrib
            ),
            None,
        )
        if message is None:
            continue
        occurred_at = _parse_datetime(message.attrib.get("UtcTime")) or datetime.now(timezone.utc)
        source = _simple_items(message, "Source")
        data = _simple_items(message, "Data")
        notifications.append(
            OnvifNotification(
                topic=topic.strip(),
                occurred_at=occurred_at,
                event_type=normalize_onvif_event_type(topic, data),
                property_operation=message.attrib.get("PropertyOperation"),
                source=source,
                data=data,
                active=_notification_active(data),
            )
        )
    return notifications


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text_in(element: ET.Element, local_name: str) -> str | None:
    for node in element.iter():
        if _local_name(node.tag) == local_name and node.text:
            value = node.text.strip()
            if value:
                return value
    return None


def _xml_root(xml: str | bytes) -> ET.Element:
    try:
        return ET.fromstring(xml)
    except ET.ParseError as exc:
        raise OnvifError("invalid ONVIF XML response") from exc


def parse_device_information(xml: str | bytes) -> dict[str, str | None]:
    root = _xml_root(xml)
    fields = {
        "manufacturer": "Manufacturer",
        "model": "Model",
        "firmware_version": "FirmwareVersion",
        "serial_number": "SerialNumber",
        "hardware_id": "HardwareId",
    }
    return {key: _text_in(root, tag) for key, tag in fields.items()}


def parse_capabilities(xml: str | bytes) -> dict[str, Any]:
    root = _xml_root(xml)
    result: dict[str, Any] = {
        "media_xaddr": None,
        "events_xaddr": None,
        "ptz_xaddr": None,
    }
    mapping = {"Media": "media_xaddr", "Events": "events_xaddr", "PTZ": "ptz_xaddr"}
    for node in root.iter():
        key = mapping.get(_local_name(node.tag))
        if key:
            result[key] = _text_in(node, "XAddr")
    return result


def _int_text(element: ET.Element, name: str) -> int | None:
    value = _text_in(element, name)
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _float_text(element: ET.Element, name: str) -> float | None:
    value = _text_in(element, name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_profiles(xml: str | bytes) -> list[dict[str, Any]]:
    root = _xml_root(xml)
    profiles: list[dict[str, Any]] = []
    for node in root.iter():
        if _local_name(node.tag) != "Profiles":
            continue
        token = (node.attrib.get("token") or "").strip()
        if not token:
            continue
        encoder = next(
            (child for child in node.iter() if _local_name(child.tag) == "VideoEncoderConfiguration"),
            None,
        )
        profiles.append(
            {
                "token": token,
                "name": _text_in(node, "Name") or token,
                "encoding": _text_in(encoder, "Encoding") if encoder is not None else None,
                "width": _int_text(encoder, "Width") if encoder is not None else None,
                "height": _int_text(encoder, "Height") if encoder is not None else None,
                "fps": _float_text(encoder, "FrameRateLimit") if encoder is not None else None,
            }
        )
    return profiles


def choose_profile_tokens(profiles: list[dict[str, Any]]) -> dict[str, str]:
    usable = [profile for profile in profiles if str(profile.get("token") or "").strip()]
    if not usable:
        raise OnvifError("ONVIF camera returned no media profiles")

    def area(profile: dict[str, Any]) -> int:
        return max(0, int(profile.get("width") or 0)) * max(0, int(profile.get("height") or 0))

    recording = max(usable, key=lambda profile: (area(profile), float(profile.get("fps") or 0)))
    auxiliary = min(usable, key=lambda profile: (area(profile), float(profile.get("fps") or 0)))
    recording_token = str(recording["token"])
    auxiliary_token = str(auxiliary["token"])
    return {
        "recording": recording_token,
        "preview": auxiliary_token,
        "detection": auxiliary_token,
    }


def parse_stream_uri(xml: str | bytes) -> str:
    uri = _text_in(_xml_root(xml), "Uri")
    if not uri:
        raise OnvifError("ONVIF camera returned no stream URI")
    return uri


def _authority_without_credentials(parsed) -> str:
    host = parsed.hostname or ""
    if not host:
        raise OnvifError("stream URI has no host")
    authority = f"[{host}]" if ":" in host and not host.startswith("[") else host
    if parsed.port is not None:
        authority = f"{authority}:{parsed.port}"
    return authority


def strip_uri_credentials(uri: str) -> str:
    parsed = urlsplit(uri)
    if parsed.scheme.lower() != "rtsp":
        raise OnvifError("ONVIF stream URI is not RTSP")
    return urlunsplit(
        (parsed.scheme, _authority_without_credentials(parsed), parsed.path, parsed.query, parsed.fragment)
    )


def inject_uri_credentials(uri: str, username: str, password: str) -> str:
    parsed = urlsplit(strip_uri_credentials(uri))
    user = quote(username, safe="")
    secret = quote(password, safe="")
    authority = f"{user}:{secret}@{_authority_without_credentials(parsed)}"
    return urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, parsed.fragment))


def validate_service_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise OnvifError("invalid ONVIF service URL")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise OnvifError("invalid ONVIF service URL") from exc
    return url


def _wsse_header(username: str, password: str) -> str:
    nonce = os.urandom(16)
    created = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode("utf-8") + password.encode("utf-8")).digest()
    ).decode("ascii")
    nonce_b64 = base64.b64encode(nonce).decode("ascii")
    return (
        '<wsse:Security s:mustUnderstand="1">'
        '<wsse:UsernameToken>'
        f'<wsse:Username>{escape(username)}</wsse:Username>'
        f'<wsse:Password Type="{PASSWORD_DIGEST}">{digest}</wsse:Password>'
        f'<wsse:Nonce EncodingType="{NONCE_BASE64}">{nonce_b64}</wsse:Nonce>'
        f'<wsu:Created>{created}</wsu:Created>'
        '</wsse:UsernameToken>'
        '</wsse:Security>'
    )


def _envelope(body: str, username: str, password: str) -> str:
    return (
        f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:tds="{TDS}" xmlns:trt="{TRT}" '
        f'xmlns:tev="{TEV}" xmlns:tt="{TT}" xmlns:wsnt="{WSNT}" xmlns:wsa="{WSA}" '
        f'xmlns:wsse="{WSSE}" xmlns:wsu="{WSU}">'
        f'<s:Header>{_wsse_header(username, password)}</s:Header>'
        f'<s:Body>{body}</s:Body>'
        '</s:Envelope>'
    )


def _soap_fault(xml: str) -> str | None:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    for node in root.iter():
        if _local_name(node.tag) == "Fault":
            return _text_in(node, "Text") or _text_in(node, "Reason") or "ONVIF SOAP fault"
    return None


class OnvifClient:
    def __init__(
        self,
        *,
        device_service_url: str,
        username: str,
        password: str,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.device_service_url = validate_service_url(device_service_url)
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds

    async def _call(self, url: str, action: str, body: str) -> str:
        service_url = validate_service_url(url)
        payload = _envelope(body, self.username, self.password)
        headers = {
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
            "User-Agent": "CameraRecorder/1.0",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(service_url, content=payload.encode("utf-8"), headers=headers)
        except httpx.HTTPError as exc:
            raise OnvifError(f"ONVIF request failed: {exc.__class__.__name__}") from exc
        text = response.text
        fault = _soap_fault(text)
        if response.status_code >= 400 or fault:
            raise OnvifError(fault or f"ONVIF HTTP {response.status_code}")
        return text

    async def get_device_information(self) -> dict[str, str | None]:
        xml = await self._call(
            self.device_service_url,
            f"{TDS}/GetDeviceInformation",
            "<tds:GetDeviceInformation/>",
        )
        return parse_device_information(xml)

    async def get_capabilities(self) -> dict[str, Any]:
        xml = await self._call(
            self.device_service_url,
            f"{TDS}/GetCapabilities",
            "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>",
        )
        return parse_capabilities(xml)

    async def get_profiles(self, media_url: str) -> list[dict[str, Any]]:
        xml = await self._call(media_url, f"{TRT}/GetProfiles", "<trt:GetProfiles/>")
        return parse_profiles(xml)


    async def get_event_properties(self, events_url: str) -> dict[str, list[str]]:
        xml = await self._call(
            events_url,
            f"{TEV}/EventPortType/GetEventPropertiesRequest",
            "<tev:GetEventProperties/>",
        )
        topics = parse_event_topics(xml)
        return {
            "event_topics": topics,
            "event_types": event_types_for_topics(topics),
        }

    async def create_pullpoint_subscription(
        self,
        events_url: str,
        *,
        initial_termination: str = "PT1M",
    ) -> OnvifSubscription:
        xml = await self._call(
            events_url,
            f"{TEV}/EventPortType/CreatePullPointSubscriptionRequest",
            (
                "<tev:CreatePullPointSubscription>"
                f"<tev:InitialTerminationTime>{escape(initial_termination)}</tev:InitialTerminationTime>"
                "</tev:CreatePullPointSubscription>"
            ),
        )
        return parse_subscription(xml)

    async def pull_messages(
        self,
        subscription_url: str,
        *,
        timeout: str = "PT30S",
        message_limit: int = 64,
    ) -> list[OnvifNotification]:
        safe_limit = max(1, min(int(message_limit), 256))
        xml = await self._call(
            subscription_url,
            f"{TEV}/PullPointSubscription/PullMessagesRequest",
            (
                "<tev:PullMessages>"
                f"<tev:Timeout>{escape(timeout)}</tev:Timeout>"
                f"<tev:MessageLimit>{safe_limit}</tev:MessageLimit>"
                "</tev:PullMessages>"
            ),
        )
        return parse_pull_messages(xml)

    async def renew_subscription(
        self,
        subscription_url: str,
        *,
        termination: str = "PT1M",
    ) -> datetime | None:
        xml = await self._call(
            subscription_url,
            "http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/RenewRequest",
            (
                "<wsnt:Renew>"
                f"<wsnt:TerminationTime>{escape(termination)}</wsnt:TerminationTime>"
                "</wsnt:Renew>"
            ),
        )
        return parse_renewal_time(xml)

    async def unsubscribe(self, subscription_url: str) -> None:
        await self._call(
            subscription_url,
            "http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/UnsubscribeRequest",
            "<wsnt:Unsubscribe/>",
        )

    async def get_stream_uri(self, media_url: str, profile_token: str) -> str:
        token = escape(profile_token)
        xml = await self._call(
            media_url,
            f"{TRT}/GetStreamUri",
            (
                "<trt:GetStreamUri>"
                "<trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream>"
                "<tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>"
                "</trt:StreamSetup>"
                f"<trt:ProfileToken>{token}</trt:ProfileToken>"
                "</trt:GetStreamUri>"
            ),
        )
        return strip_uri_credentials(parse_stream_uri(xml))

    async def probe(self) -> dict[str, Any]:
        identity = await self.get_device_information()
        capabilities = await self.get_capabilities()
        events_url = capabilities.get("events_xaddr")
        if isinstance(events_url, str) and events_url:
            try:
                capabilities.update(await self.get_event_properties(events_url))
            except OnvifError:
                capabilities["event_topics"] = []
                capabilities["event_types"] = []

        media_url = capabilities.get("media_xaddr")
        if not media_url:
            raise OnvifError("ONVIF camera does not advertise a Media service")
        media_url = validate_service_url(media_url)
        profiles = await self.get_profiles(media_url)
        selected = choose_profile_tokens(profiles)

        uris: dict[str, str] = {}
        enriched: list[dict[str, Any]] = []
        for profile in profiles:
            token = str(profile["token"])
            uri = await self.get_stream_uri(media_url, token)
            uris[token] = uri
            enriched.append({**profile, "uri": uri})

        return {
            **identity,
            "device_uuid": None,
            "device_service_url": self.device_service_url,
            "capabilities": capabilities,
            "profiles": enriched,
            "recording_profile_token": selected["recording"],
            "preview_profile_token": selected["preview"],
            "detection_profile_token": selected["detection"],
            "recording_uri": uris[selected["recording"]],
            "preview_uri": uris[selected["preview"]],
            "detection_uri": uris[selected["detection"]],
        }
