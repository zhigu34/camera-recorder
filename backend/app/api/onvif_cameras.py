from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.camera import (
    CameraRead,
    CameraUnifiedCreate,
    CameraUnifiedUpdate,
    OnvifCameraCreate,
    OnvifCameraUpdate,
    OnvifProbeRequest,
    OnvifProbeResult,
)
from app.schemas.camera_connection import OnvifConnectionCreate, OnvifConnectionUpdate
from app.services.camera_adapter_probe import (
    CameraConnectionProbeResult,
    _sanitize_profiles,
    _strip_uri_credentials,
)
from app.services.camera_mutation import create_unified_camera, update_unified_camera
from app.services.camera_probe import CameraProbeError, probe_stream_uri
from app.services.camera_runtime_coordinator import camera_runtime_coordinator
from app.services.onvif_client import OnvifClient, OnvifError, inject_uri_credentials
from app.services.recording_schedule_manager import recording_schedule_manager
from app.services.system_settings import load_runtime_settings

router = APIRouter(prefix="/api/cameras/onvif", tags=["onvif-cameras"])


async def _probe_onvif(payload: OnvifProbeRequest) -> OnvifProbeResult:
    client = OnvifClient(
        device_service_url=payload.device_service_url,
        username=payload.username,
        password=payload.password,
    )
    try:
        value = await client.probe()
    except OnvifError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return OnvifProbeResult.model_validate(value)


async def _probe_legacy_connection(
    payload: OnvifProbeRequest,
    db: AsyncSession,
) -> tuple[OnvifProbeResult, CameraConnectionProbeResult]:
    discovered = await _probe_onvif(payload)
    runtime = await load_runtime_settings(db)
    try:
        media = await probe_stream_uri(
            stream_uri=inject_uri_credentials(
                discovered.recording_uri,
                payload.username,
                payload.password,
            ),
            rtsp_timeout_us=runtime.rtsp_timeout_us,
        )
    except CameraProbeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"ONVIF 设备可访问，但主码流验证失败: {exc}",
        ) from exc

    result = CameraConnectionProbeResult(
        adapter="onvif",
        device={
            "manufacturer": discovered.manufacturer,
            "model": discovered.model,
            "firmware_version": discovered.firmware_version,
            "serial_number": discovered.serial_number,
            "hardware_id": discovered.hardware_id,
        },
        media=media,
        connection_cache={
            "device_service_url": discovered.device_service_url,
            "device_uuid": discovered.device_uuid,
            "capabilities": discovered.capabilities,
            "profiles": _sanitize_profiles([item.model_dump() for item in discovered.profiles]),
            "recording_profile_token": discovered.recording_profile_token,
            "preview_profile_token": discovered.preview_profile_token,
            "detection_profile_token": discovered.detection_profile_token,
            "recording_uri": _strip_uri_credentials(discovered.recording_uri),
            "preview_uri": _strip_uri_credentials(discovered.preview_uri),
            "detection_uri": _strip_uri_credentials(discovered.detection_uri),
        },
    )
    return discovered, result


@router.post("/probe", response_model=OnvifProbeResult)
async def probe_onvif_camera(payload: OnvifProbeRequest):
    return await _probe_onvif(payload)


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
async def create_onvif_camera(
    payload: OnvifCameraCreate,
    db: AsyncSession = Depends(get_db),
):
    discovered, probe_result = await _probe_legacy_connection(payload, db)
    unified = CameraUnifiedCreate(
        name=payload.name,
        manufacturer=discovered.manufacturer,
        model=discovered.model,
        form_factor=payload.form_factor,
        enabled=payload.enabled,
        auto_record=payload.auto_record,
        timestamp_mode=payload.timestamp_mode,
        connection=OnvifConnectionCreate(
            host=payload.host,
            port=payload.port,
            username=payload.username,
            password=payload.password,
        ),
    )
    camera = await create_unified_camera(unified, db, probe_result=probe_result)
    recording_schedule_manager.reset_for_schedule_change(camera.id)
    await recording_schedule_manager.reconcile()
    return camera


@router.put("/{camera_id}", response_model=CameraRead)
async def update_onvif_camera(
    camera_id: int,
    payload: OnvifCameraUpdate,
    db: AsyncSession = Depends(get_db),
):
    discovered, probe_result = await _probe_legacy_connection(payload, db)
    values = {
        "manufacturer": discovered.manufacturer,
        "model": discovered.model,
        "connection": OnvifConnectionUpdate(
            host=payload.host,
            port=payload.port,
            username=payload.username,
            password=payload.password,
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
