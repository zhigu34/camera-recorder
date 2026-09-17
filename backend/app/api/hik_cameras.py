from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.camera import CameraRead, CameraUnifiedCreate, CameraUnifiedUpdate
from app.schemas.camera_connection import HikConnectionCreate, HikConnectionUpdate
from app.schemas.hikvision import HikCameraCreate, HikCameraUpdate, HikProbeRequest, HikProbeResult
from app.services.camera_adapter_probe import CameraConnectionProbeResult
from app.services.camera_mutation import create_unified_camera, update_unified_camera
from app.services.camera_probe import CameraProbeError, probe_stream_uri
from app.services.camera_runtime_coordinator import camera_runtime_coordinator
from app.services.hik_bridge_client import HikBridgeClient, HikBridgeClientError
from app.services.hik_media_adapter import HikBridgeTarget
from app.services.recording_schedule_manager import recording_schedule_manager
from app.services.system_settings import load_runtime_settings

router = APIRouter(prefix="/api/cameras/hik", tags=["hik-cameras"])


def _bridge_http_status(exc: HikBridgeClientError) -> int:
    code = exc.status_code
    if code is not None and 400 <= code < 600:
        return code
    return 502


async def _probe_hik(payload: HikProbeRequest) -> HikProbeResult:
    client = HikBridgeClient()
    try:
        value = await client.probe(
            host=payload.host,
            port=payload.port,
            username=payload.username,
            password=payload.password,
        )
    except HikBridgeClientError as exc:
        raise HTTPException(status_code=_bridge_http_status(exc), detail=str(exc)) from exc
    value = dict(value)
    value["channel"] = payload.channel
    return HikProbeResult.model_validate(value)


async def _validate_main_stream(payload: HikProbeRequest, db: AsyncSession) -> dict:
    runtime = await load_runtime_settings(db)
    client = HikBridgeClient()
    target = HikBridgeTarget(
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        channel=payload.channel,
        stream_type=0,
    )
    stream_id: str | None = None
    try:
        stream_id = await client.create_stream(target)
        return await probe_stream_uri(
            stream_uri=client.media_url(stream_id),
            rtsp_timeout_us=runtime.rtsp_timeout_us,
        )
    except HikBridgeClientError as exc:
        raise HTTPException(status_code=_bridge_http_status(exc), detail=str(exc)) from exc
    except CameraProbeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"HIK SDK 登录成功，但主码流验证失败: {exc}",
        ) from exc
    finally:
        if stream_id:
            with suppress(Exception):
                await client.stop_stream(stream_id)


async def _probe_legacy_connection(
    payload: HikProbeRequest,
    db: AsyncSession,
) -> tuple[HikProbeResult, CameraConnectionProbeResult]:
    discovered = await _probe_hik(payload)
    media = await _validate_main_stream(payload, db)
    return discovered, CameraConnectionProbeResult(
        adapter="hik_sdk",
        device=discovered.model_dump(exclude={"ok", "channel"}, exclude_none=True),
        media=media,
        connection_cache={
            "sdk_port": payload.port,
            "channel": payload.channel,
            "main_stream_type": 0,
            "sub_stream_type": 1,
            "device_serial": discovered.serial_number,
            "device_model": discovered.device_model,
            "device_name": discovered.device_name,
        },
    )


def _model_name(discovered: HikProbeResult, fallback: str | None = None) -> str | None:
    if discovered.device_model:
        return discovered.device_model
    if discovered.device_type is not None:
        return f"HIK device type {discovered.device_type}"
    return fallback


@router.post("/probe", response_model=HikProbeResult)
async def probe_hik_camera(payload: HikProbeRequest):
    return await _probe_hik(payload)


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
async def create_hik_camera(
    payload: HikCameraCreate,
    db: AsyncSession = Depends(get_db),
):
    discovered, probe_result = await _probe_legacy_connection(payload, db)
    unified = CameraUnifiedCreate(
        name=payload.name,
        manufacturer="Hikvision",
        model=_model_name(discovered),
        form_factor=payload.form_factor,
        enabled=payload.enabled,
        auto_record=payload.auto_record,
        timestamp_mode=payload.timestamp_mode,
        connection=HikConnectionCreate(
            host=payload.host,
            sdk_port=payload.port,
            username=payload.username,
            password=payload.password,
            channel=payload.channel,
            main_stream_type=0,
            sub_stream_type=1,
        ),
    )
    camera = await create_unified_camera(unified, db, probe_result=probe_result)
    recording_schedule_manager.reset_for_schedule_change(camera.id)
    await recording_schedule_manager.reconcile()
    return camera


@router.put("/{camera_id}", response_model=CameraRead)
async def update_hik_camera(
    camera_id: int,
    payload: HikCameraUpdate,
    db: AsyncSession = Depends(get_db),
):
    discovered, probe_result = await _probe_legacy_connection(payload, db)
    values = {
        "manufacturer": "Hikvision",
        "model": _model_name(discovered),
        "connection": HikConnectionUpdate(
            host=payload.host,
            sdk_port=payload.port,
            username=payload.username,
            password=payload.password,
            channel=payload.channel,
            main_stream_type=0,
            sub_stream_type=1,
        ),
    }
    for field in ("name", "form_factor", "enabled", "auto_record", "timestamp_mode"):
        value = getattr(payload, field)
        if value is not None:
            values[field] = value

    unified = CameraUnifiedUpdate.model_validate(values)
    return await update_unified_camera(
        camera_id,
        unified,
        db,
        probe_result=probe_result,
        coordinator=camera_runtime_coordinator,
    )
