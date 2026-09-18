from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone
from html import escape
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import httpx

SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
TDS = "http://www.onvif.org/ver10/device/wsdl"
TRT = "http://www.onvif.org/ver10/media/wsdl"
TT = "http://www.onvif.org/ver10/schema"
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


def parse_capabilities(xml: str | bytes) -> dict[str, str | None]:
    root = _xml_root(xml)
    result: dict[str, str | None] = {
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


def _validate_service_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise OnvifError("invalid ONVIF service URL")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise OnvifError("invalid ONVIF service URL") from exc
    return url


def validate_service_url(url: str) -> str:
    return _validate_service_url(url)


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
        f'xmlns:tt="{TT}" xmlns:wsse="{WSSE}" xmlns:wsu="{WSU}">'
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
        self.device_service_url = _validate_service_url(device_service_url)
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds

    async def _call(self, url: str, action: str, body: str) -> str:
        service_url = _validate_service_url(url)
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

    async def get_capabilities(self) -> dict[str, str | None]:
        xml = await self._call(
            self.device_service_url,
            f"{TDS}/GetCapabilities",
            "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>",
        )
        return parse_capabilities(xml)

    async def get_profiles(self, media_url: str) -> list[dict[str, Any]]:
        xml = await self._call(media_url, f"{TRT}/GetProfiles", "<trt:GetProfiles/>")
        return parse_profiles(xml)

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
        media_url = capabilities.get("media_xaddr")
        if not media_url:
            raise OnvifError("ONVIF camera does not advertise a Media service")
        media_url = _validate_service_url(media_url)
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
