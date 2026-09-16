from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any, Callable

from hik_bridge.hcnet_types import (
    C_BOOL,
    C_DWORD,
    C_LONG,
    NET_DVR_DEVICEINFO_V40,
    NET_DVR_LOCAL_SDK_PATH,
    NET_DVR_PREVIEWINFO,
    NET_DVR_STREAMDATA,
    NET_DVR_SYSHEAD,
    NET_DVR_USER_LOGIN_INFO,
    REALDATA_CALLBACK,
)
from hik_bridge.service import HikBridgeError


def _component_directory(root: Path) -> Path:
    """Return the vendor component-library directory for NET_DVR_SetSDKInitCfg."""

    candidate = root / "HCNetSDKCom"
    return candidate if candidate.is_dir() else root


def _find_runtime_library(root: Path, stem: str) -> Path | None:
    """Find a vendor runtime library without assuming one OpenSSL SONAME."""

    for directory in (root, root / "HCNetSDKCom"):
        if not directory.is_dir():
            continue
        exact = directory / stem
        if exact.is_file():
            return exact
        matches = sorted(
            (path for path in directory.glob(f"{stem}.*") if path.is_file()),
            key=lambda path: path.name,
        )
        if matches:
            return matches[0]
    return None


def _preview_info(*, channel: int, stream_type: int) -> NET_DVR_PREVIEWINFO:
    preview = NET_DVR_PREVIEWINFO()
    preview.lChannel = int(channel)
    preview.dwStreamType = int(stream_type)
    preview.dwLinkMode = 0
    preview.hPlayWnd = 0
    # Blocking startup gives create_stream an immediate success/failure result.
    preview.bBlocked = 1
    # ANR record passback can inject historical device recordings after a link
    # recovers; the bridge must expose only the live stream to the shared pipeline.
    preview.bPassbackRecord = 0
    return preview


class HcNetSdk:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.getenv("HIK_SDK_PATH", "/opt/hikvision/runtime"))
        self.library_path = self.root / "libhcnetsdk.so"
        self.runtime_available = self.library_path.is_file()
        self._lib = None
        self._callbacks: dict[int, Any] = {}
        self._initialized = False

    def _error(self, message: str) -> HikBridgeError:
        code = int(self._lib.NET_DVR_GetLastError()) if self._lib is not None else None
        return HikBridgeError(message, code=code)

    def _load(self):
        if not self.runtime_available:
            raise HikBridgeError("HCNetSDK runtime is unavailable")
        if self._lib is None:
            self._lib = ctypes.CDLL(str(self.library_path))
            self._lib.NET_DVR_Init.restype = C_BOOL
            self._lib.NET_DVR_Cleanup.restype = C_BOOL
            self._lib.NET_DVR_GetLastError.restype = C_DWORD
            self._lib.NET_DVR_Login_V40.argtypes = [
                ctypes.POINTER(NET_DVR_USER_LOGIN_INFO),
                ctypes.POINTER(NET_DVR_DEVICEINFO_V40),
            ]
            self._lib.NET_DVR_Login_V40.restype = C_LONG
            self._lib.NET_DVR_Logout.argtypes = [C_LONG]
            self._lib.NET_DVR_Logout.restype = C_BOOL
            self._lib.NET_DVR_RealPlay_V40.argtypes = [
                C_LONG,
                ctypes.POINTER(NET_DVR_PREVIEWINFO),
                REALDATA_CALLBACK,
                ctypes.c_void_p,
            ]
            self._lib.NET_DVR_RealPlay_V40.restype = C_LONG
            self._lib.NET_DVR_StopRealPlay.argtypes = [C_LONG]
            self._lib.NET_DVR_StopRealPlay.restype = C_BOOL
            if hasattr(self._lib, "NET_DVR_SetSDKInitCfg"):
                self._lib.NET_DVR_SetSDKInitCfg.argtypes = [C_DWORD, ctypes.c_void_p]
                self._lib.NET_DVR_SetSDKInitCfg.restype = C_BOOL
        return self._lib

    def initialize(self) -> None:
        if self._initialized:
            return
        lib = self._load()
        if hasattr(lib, "NET_DVR_SetSDKInitCfg"):
            sdk_path = NET_DVR_LOCAL_SDK_PATH()
            component_bytes = str(_component_directory(self.root)).encode("utf-8")
            sdk_path.sPath = component_bytes[:255]
            lib.NET_DVR_SetSDKInitCfg(2, ctypes.byref(sdk_path))

            # Hikvision runtimes have shipped with different OpenSSL SONAMEs.
            # Configure the vendor library that is actually present instead of
            # assuming the host/container OpenSSL major version.
            for command, stem in ((3, "libcrypto.so"), (4, "libssl.so")):
                candidate = _find_runtime_library(self.root, stem)
                if candidate is None:
                    continue
                path_buffer = ctypes.create_string_buffer(str(candidate).encode("utf-8"))
                lib.NET_DVR_SetSDKInitCfg(
                    command,
                    ctypes.cast(path_buffer, ctypes.c_void_p),
                )
        if not lib.NET_DVR_Init():
            raise self._error("HCNetSDK initialization failed")
        self._initialized = True

    def cleanup(self) -> None:
        if not self._initialized or self._lib is None:
            return
        self._lib.NET_DVR_Cleanup()
        self._callbacks.clear()
        self._initialized = False

    @staticmethod
    def _bounded(value: str, limit: int, field: str) -> bytes:
        encoded = value.encode("utf-8")
        if len(encoded) >= limit:
            raise HikBridgeError(f"{field} is too long")
        return encoded

    def login(
        self, host: str, port: int, username: str, password: str
    ) -> tuple[int, dict[str, Any]]:
        lib = self._load()
        info = NET_DVR_USER_LOGIN_INFO()
        info.sDeviceAddress = self._bounded(host, 129, "host")
        info.wPort = int(port)
        info.sUserName = self._bounded(username, 64, "username")
        info.sPassword = self._bounded(password, 64, "password")
        info.bUseAsynLogin = 0
        info.byLoginMode = 0
        device = NET_DVR_DEVICEINFO_V40()
        user_id = int(lib.NET_DVR_Login_V40(ctypes.byref(info), ctypes.byref(device)))
        if user_id < 0:
            raise self._error("SDK login failed")
        serial = (
            bytes(device.struDeviceV30.sSerialNumber)
            .split(b"\0", 1)[0]
            .decode("utf-8", "replace")
        )
        return user_id, {
            "serial_number": serial or None,
            "device_type": int(device.struDeviceV30.wDevType),
            "start_channel": int(device.struDeviceV30.byStartChan),
            "analog_channel_count": int(device.struDeviceV30.byChanNum),
            "digital_channel_count": (
                int(device.struDeviceV30.byIPChanNum)
                + int(device.struDeviceV30.byHighDChanNum) * 256
            ),
        }

    def logout(self, user_id: int) -> None:
        if self._lib is not None and user_id >= 0:
            self._lib.NET_DVR_Logout(user_id)

    def start_realplay(
        self,
        user_id: int,
        channel: int,
        stream_type: int,
        callback: Callable[[bytes], None],
    ) -> int:
        lib = self._load()
        preview = _preview_info(channel=channel, stream_type=stream_type)

        def _native(_handle, data_type, buffer, size, _user) -> None:
            if (
                data_type not in (NET_DVR_SYSHEAD, NET_DVR_STREAMDATA)
                or not buffer
                or size <= 0
            ):
                return
            callback(ctypes.string_at(buffer, int(size)))

        native_callback = REALDATA_CALLBACK(_native)
        handle = int(
            lib.NET_DVR_RealPlay_V40(
                user_id,
                ctypes.byref(preview),
                native_callback,
                None,
            )
        )
        if handle < 0:
            raise self._error("SDK real-play start failed")
        self._callbacks[handle] = native_callback
        return handle

    def stop_realplay(self, handle: int) -> None:
        try:
            if self._lib is not None and handle >= 0:
                self._lib.NET_DVR_StopRealPlay(handle)
        finally:
            self._callbacks.pop(handle, None)
