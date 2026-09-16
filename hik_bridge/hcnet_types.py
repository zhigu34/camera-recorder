from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    c_byte,
    c_char,
    c_long,
    c_uint16,
    c_uint32,
    c_ubyte,
    c_ulong,
    c_void_p,
)

NET_DVR_SYSHEAD = 1
NET_DVR_STREAMDATA = 2


class NET_DVR_DEVICEINFO_V30(Structure):
    _fields_ = [
        ("sSerialNumber", c_ubyte * 48),
        ("byAlarmInPortNum", c_byte),
        ("byAlarmOutPortNum", c_byte),
        ("byDiskNum", c_byte),
        ("byDVRType", c_byte),
        ("byChanNum", c_byte),
        ("byStartChan", c_byte),
        ("byAudioChanNum", c_byte),
        ("byIPChanNum", c_byte),
        ("byZeroChanNum", c_byte),
        ("byMainProto", c_byte),
        ("bySubProto", c_byte),
        ("bySupport", c_byte),
        ("bySupport1", c_byte),
        ("bySupport2", c_byte),
        ("wDevType", c_uint16),
        ("bySupport3", c_byte),
        ("byMultiStreamProto", c_byte),
        ("byStartDChan", c_byte),
        ("byStartDTalkChan", c_byte),
        ("byHighDChanNum", c_byte),
        ("bySupport4", c_byte),
        ("byLanguageType", c_byte),
        ("byVoiceInChanNum", c_byte),
        ("byStartVoiceInChanNo", c_byte),
        ("bySupport5", c_byte),
        ("bySupport6", c_byte),
        ("byMirrorChanNum", c_byte),
        ("wStartMirrorChanNo", c_uint16),
        ("bySupport7", c_byte),
        ("byRes2", c_byte),
    ]


class NET_DVR_DEVICEINFO_V40(Structure):
    _fields_ = [
        ("struDeviceV30", NET_DVR_DEVICEINFO_V30),
        ("bySupportLock", c_byte),
        ("byRetryLoginTime", c_byte),
        ("byPasswordLevel", c_byte),
        ("byProxyType", c_byte),
        ("dwSurplusLockTime", c_uint32),
        ("byCharEncodeType", c_byte),
        ("bySupportDev5", c_byte),
        ("bySupport", c_byte),
        ("byLoginMode", c_byte),
        ("dwOEMCode", c_uint32),
        ("iResidualValidity", c_uint32),
        ("byResidualValidity", c_byte),
        ("bySingleStartDTalkChan", c_byte),
        ("bySingleDTalkChanNums", c_byte),
        ("byPassWordResetLevel", c_byte),
        ("bySupportStreamEncrypt", c_byte),
        ("byMarketType", c_byte),
        ("byRes2", c_byte * 238),
    ]


LOGIN_RESULT_CALLBACK = CFUNCTYPE(
    None,
    c_uint32,
    c_uint32,
    POINTER(NET_DVR_DEVICEINFO_V30),
    c_void_p,
)


class NET_DVR_USER_LOGIN_INFO(Structure):
    _fields_ = [
        ("sDeviceAddress", c_char * 129),
        ("byUseTransport", c_byte),
        ("wPort", c_uint16),
        ("sUserName", c_char * 64),
        ("sPassword", c_char * 64),
        ("cbLoginResult", LOGIN_RESULT_CALLBACK),
        ("pUser", c_void_p),
        ("bUseAsynLogin", c_uint32),
        ("byProxyType", c_byte),
        ("byUseUTCTime", c_byte),
        ("byLoginMode", c_byte),
        ("byHttps", c_byte),
        ("iProxyID", c_uint32),
        ("byVerifyMode", c_byte),
        ("byRes2", c_byte * 119),
    ]


class NET_DVR_LOCAL_SDK_PATH(Structure):
    _fields_ = [("sPath", c_char * 256), ("byRes", c_byte * 128)]


class NET_DVR_PREVIEWINFO(Structure):
    _fields_ = [
        ("lChannel", c_uint32),
        ("dwStreamType", c_uint32),
        ("dwLinkMode", c_uint32),
        ("hPlayWnd", c_uint32),
        ("bBlocked", c_uint32),
        ("bPassbackRecord", c_uint32),
        ("byPreviewMode", c_ubyte),
        ("byStreamID", c_ubyte * 32),
        ("byProtoType", c_ubyte),
        ("byRes1", c_ubyte),
        ("byVideoCodingType", c_ubyte),
        ("dwDisplayBufNum", c_uint32),
        ("byNPQMode", c_ubyte),
        ("byRecvMetaData", c_ubyte),
        ("byDataType", c_ubyte),
        ("byRes", c_ubyte * 213),
    ]


REALDATA_CALLBACK = CFUNCTYPE(
    None,
    c_long,
    c_ulong,
    POINTER(c_ubyte),
    c_ulong,
    c_void_p,
)
