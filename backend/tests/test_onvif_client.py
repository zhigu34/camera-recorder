from app.services.onvif_client import (
    choose_profile_tokens,
    inject_uri_credentials,
    parse_capabilities,
    parse_device_information,
    parse_profiles,
    parse_stream_uri,
    strip_uri_credentials,
)


DEVICE_INFORMATION_XML = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
  <s:Body><tds:GetDeviceInformationResponse>
    <tds:Manufacturer>Acme</tds:Manufacturer><tds:Model>Cam X</tds:Model>
    <tds:FirmwareVersion>1.2.3</tds:FirmwareVersion><tds:SerialNumber>SN123</tds:SerialNumber>
    <tds:HardwareId>HW9</tds:HardwareId>
  </tds:GetDeviceInformationResponse></s:Body>
</s:Envelope>"""

CAPABILITIES_XML = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body><tds:GetCapabilitiesResponse><tds:Capabilities>
    <tt:Media><tt:XAddr>http://10.0.0.20/onvif/media_service</tt:XAddr></tt:Media>
    <tt:Events><tt:XAddr>http://10.0.0.20/onvif/events_service</tt:XAddr></tt:Events>
    <tt:PTZ><tt:XAddr>http://10.0.0.20/onvif/ptz_service</tt:XAddr></tt:PTZ>
  </tds:Capabilities></tds:GetCapabilitiesResponse></s:Body>
</s:Envelope>"""

PROFILES_XML = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body><trt:GetProfilesResponse>
    <trt:Profiles token="main"><tt:Name>Main</tt:Name><tt:VideoEncoderConfiguration>
      <tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>
      <tt:RateControl><tt:FrameRateLimit>25</tt:FrameRateLimit></tt:RateControl>
    </tt:VideoEncoderConfiguration></trt:Profiles>
    <trt:Profiles token="sub"><tt:Name>Sub</tt:Name><tt:VideoEncoderConfiguration>
      <tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>640</tt:Width><tt:Height>360</tt:Height></tt:Resolution>
      <tt:RateControl><tt:FrameRateLimit>10</tt:FrameRateLimit></tt:RateControl>
    </tt:VideoEncoderConfiguration></trt:Profiles>
  </trt:GetProfilesResponse></s:Body>
</s:Envelope>"""

STREAM_URI_XML = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body><trt:GetStreamUriResponse><trt:MediaUri>
    <tt:Uri>rtsp://admin:secret@10.0.0.20:554/Streaming/Channels/101?transportmode=unicast</tt:Uri>
  </trt:MediaUri></trt:GetStreamUriResponse></s:Body>
</s:Envelope>"""


def test_parse_device_information_and_capabilities() -> None:
    info = parse_device_information(DEVICE_INFORMATION_XML)
    capabilities = parse_capabilities(CAPABILITIES_XML)

    assert info == {
        "manufacturer": "Acme",
        "model": "Cam X",
        "firmware_version": "1.2.3",
        "serial_number": "SN123",
        "hardware_id": "HW9",
    }
    assert capabilities["media_xaddr"] == "http://10.0.0.20/onvif/media_service"
    assert capabilities["events_xaddr"] == "http://10.0.0.20/onvif/events_service"
    assert capabilities["ptz_xaddr"] == "http://10.0.0.20/onvif/ptz_service"


def test_profiles_choose_largest_for_recording_and_smallest_for_auxiliary() -> None:
    profiles = parse_profiles(PROFILES_XML)
    selected = choose_profile_tokens(profiles)

    assert profiles[0]["token"] == "main"
    assert profiles[0]["width"] == 1920
    assert profiles[0]["fps"] == 25.0
    assert selected == {
        "recording": "main",
        "preview": "sub",
        "detection": "sub",
    }


def test_onvif_stream_uri_is_stored_without_credentials_and_injected_at_runtime() -> None:
    uri = parse_stream_uri(STREAM_URI_XML)
    stored = strip_uri_credentials(uri)
    runtime = inject_uri_credentials(stored, "operator@site", "p:ss/word")

    assert stored == "rtsp://10.0.0.20:554/Streaming/Channels/101?transportmode=unicast"
    assert runtime == "rtsp://operator%40site:p%3Ass%2Fword@10.0.0.20:554/Streaming/Channels/101?transportmode=unicast"
    assert "secret" not in stored
