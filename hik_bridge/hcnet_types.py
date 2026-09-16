from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    c_char,
    c_int,
    c_uint,
    c_ubyte,
    c_ushort,
    c_void_p,
)

# HCNetSDK defines LONG/DWORD/BOOL as 32-bit values on Linux64. Do not use
# ctypes.c_long/c_ulong here because LP64 platforms make those 64-bit.
C_LONG = c_int
C_DWORD = c_uint
C_BOOL = c_int
C_BYTE = c_ubyte
C_WORD = c_ushort
C_HWND = c_uint

NET_DVR_SYSHEAD = 1
NET_DVR_STREAMDATA = 2


class NET_DVR_DEVICEINFO_V30(Structure):
    _fields_ = [
        ("sSerialNumber", C_BYTE * 48),
        ("byAlarmInPortNum", C_BYTE),
        ("byAlarmOutPortNum", C_BYTE),
        ("byDiskNum", C_BYTE),
        ("byDVRType", C_BYTE),
        ("byChanNum", C_BYTE),
        ("byStartChan", C_BYTE),
        ("byAudioChanNum", C_BYTE),
        ("byIPChanNum", C_BYTE),
        ("byZeroChanNum", C_BYTE),
        ("byMainProto", C_BYTE),
        ("bySubProto", C_BYTE),
        ("bySupport", C_BYTE),
        ("bySupport1", C_BYTE),
        ("bySupport2", C_BYTE),
        ("wDevType", C_WORD),
        ("bySupport3", C_BYTE),
        ("byMultiStreamProto", C_BYTE),
        ("byStartDChan", C_BYTE),
        ("byStartDTalkChan", C_BYTE),
        ("byHighDChanNum", C_BYTE),
        ("bySupport4", C_BYTE),
        ("byLanguageType", C_BYTE),
        ("byVoiceInChanNum", C_BYTE),
        ("byStartVoiceInChanNo", C_BYTE),
        ("bySupport5", C_BYTE),
        ("bySupport6", C_BYTE),
        ("byMirrorChanNum", C_BYTE),
        ("wStartMirrorChanNo", C_WORD),
        ("bySupport7", C_BYTE),
        ("byRes2", C_BYTE),
    ]


class NET_DVR_DEVICEINFO_V40(Structure):
    _fields_ = [
        ("struDeviceV30", NET_DVR_DEVICEINFO_V30),
        ("bySupportLock", C_BYTE),
        ("byRetryLoginTime", C_BYTE),
        ("byPasswordLevel", C_BYTE),
        ("byProxyType", C_BYTE),
        ("dwSurplusLockTime", C_DWORD),
        ("byCharEncodeType", C_BYTE),
        ("bySupportDev5", C_BYTE),
        ("bySupport", C_BYTE),
        ("byLoginMode", C_BYTE),
        ("dwOEMCode", C_DWORD),
        ("iResidualValidity", C_LONG),
        ("byResidualValidity", C_BYTE),
        ("bySingleStartDTalkChan", C_BYTE),
        ("bySingleDTalkChanNums", C_BYTE),
        ("byPassWordResetLevel", C_BYTE),
        ("bySupportStreamEncrypt", C_BYTE),
        ("byMarketType", C_BYTE),
        ("byRes2", C_BYTE * 238),
    ]


LOGIN_RESULT_CALLBACK = CFUNCTYPE(
    None,
    C_LONG,
    C_DWORD,
    POINTER(NET_DVR_DEVICEINFO_V30),
    c_void_p,
)


class NET_DVR_USER_LOGIN_INFO(Structure):
    _fields_ = [
        ("sDeviceAddress", c_char * 129),
        ("byUseTransport", C_BYTE),
        ("wPort", C_WORD),
        ("sUserName", c_char * 64),
        ("sPassword", c_char * 64),
        ("cbLoginResult", LOGIN_RESULT_CALLBACK),
        ("pUser", c_void_p),
        ("bUseAsynLogin", C_BOOL),
        ("byProxyType", C_BYTE),
        ("byUseUTCTime", C_BYTE),
        ("byLoginMode", C_BYTE),
        ("byHttps", C_BYTE),
        ("iProxyID", C_LONG),
        ("byVerifyMode", C_LONG),
        ("byRes3", C_BYTE * 119),
    ]


class NET_DVR_LOCAL_SDK_PATH(Structure):
    _fields_ = [("sPath", c_char * 256), ("byRes", C_BYTE * 128)]


class NET_DVR_PREVIEWINFO(Structure):
    _fields_ = [
        ("lChannel", C_LONG),
        ("dwStreamType", C_DWORD),
        ("dwLinkMode", C_DWORD),
        ("hPlayWnd", C_HWND),
        ("bBlocked", C_BOOL),
        ("bPassbackRecord", C_BOOL),
        ("byPreviewMode", C_BYTE),
        ("byStreamID", C_BYTE * 32),
        ("byProtoType", C_BYTE),
        ("byRes1", C_BYTE),
        ("byVideoCodingType", C_BYTE),
        ("dwDisplayBufNum", C_DWORD),
        ("byNPQMode", C_BYTE),
        ("byRecvMetaData", C_BYTE),
        ("byDataType", C_BYTE),
        ("byRes", C_BYTE * 213),
    ]


REALDATA_CALLBACK = CFUNCTYPE(
    None,
    C_LONG,
    C_DWORD,
    POINTER(C_BYTE),
    C_DWORD,
    c_void_p,
)
