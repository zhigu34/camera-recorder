from ctypes import c_int, c_ubyte, c_uint

from hik_bridge.hcnet_types import (
    NET_DVR_DEVICEINFO_V30,
    NET_DVR_USER_LOGIN_INFO,
    REALDATA_CALLBACK,
)


def _field_type(structure, name: str):
    return dict(structure._fields_)[name]


def test_login_verify_mode_uses_32_bit_long() -> None:
    assert _field_type(NET_DVR_USER_LOGIN_INFO, "byVerifyMode") is c_int


def test_realdata_callback_uses_linux_sdk_fixed_width_long_and_dword() -> None:
    args = REALDATA_CALLBACK._argtypes_
    assert args[0] is c_int
    assert args[1] is c_uint
    assert args[3] is c_uint


def test_device_info_byte_counts_are_unsigned() -> None:
    assert _field_type(NET_DVR_DEVICEINFO_V30, "byIPChanNum") is c_ubyte
    info = NET_DVR_DEVICEINFO_V30()
    info.byIPChanNum = 200
    assert info.byIPChanNum == 200
