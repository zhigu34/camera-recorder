from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_secret
from app.models.camera import Camera
from app.schemas.camera import CameraUnifiedCreate, CameraUnifiedUpdate
from app.schemas.camera_connection import (
    HikConnectionCreate,
    ManualRtspConnectionCreate,
    ManualRtspConnectionUpdate,
    OnvifConnectionCreate,
    OnvifConnectionUpdate,
)
from app.services.camera_adapter_probe import CameraConnectionProbeResult, apply_probe_success
from app.services.camera_connection import (
    switch_to_hik_connection,
    switch_to_manual_rtsp_connection,
    switch_to_onvif_connection,
    upsert_hik_connection,
    upsert_manual_rtsp_connection,
    upsert_onvif_connection,
)
from app.services.camera_identity import infer_camera_form_factor
from app.services.camera_runtime_coordinator import camera_runtime_coordinator
from app.services.event_log import add_audit_event, add_event

_RUNTIME_POLICY_FIELDS = {
    "enabled",
    "auto_record",
    "recording_schedule_enabled",
    "recording_schedule",
    "timestamp_mode",
}
_SCHEDULE_FIELDS = {
    "auto_record",
    "recording_schedule_enabled",
    "recording_schedule",
}


def _resolved_form_factor(manufacturer: str | None, model: str | None, requested: str) -> str:
    if requested != "unknown":
        return requested
    guess = infer_camera_form_factor(manufacturer, model)
    if guess is not None and guess.confidence == "high":
        return guess.form_factor
    return requested


def _onvif_device_service_url(
    host: str,
    port: int,
    explicit_url: str | None = None,
) -> str:
    if explicit_url:
        return explicit_url
    authority = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{authority}:{port}/onvif/device_service"


def _seed_camera(payload: CameraUnifiedCreate, password_encrypted: str) -> Camera:
    connection = payload.connection
    if isinstance(connection, ManualRtspConnectionCreate):
        ip = connection.host
        rtsp_port = connection.port
        rtsp_path = connection.main_path
        sub_rtsp_path = connection.sub_path
    elif isinstance(connection, OnvifConnectionCreate):
        ip = connection.host
        rtsp_port = 554
        rtsp_path = "/"
        sub_rtsp_path = None
    else:
        assert isinstance(connection, HikConnectionCreate)
        ip = connection.host
        rtsp_port = 554
        rtsp_path = "/hik-sdk/main"
        sub_rtsp_path = "/hik-sdk/sub"

    return Camera(
        name=payload.name,
        manufacturer=payload.manufacturer,
        model=payload.model,
        form_factor=_resolved_form_factor(
            payload.manufacturer,
            payload.model,
            payload.form_factor,
        ),
        connection_type=connection.adapter,
        ip=ip,
        rtsp_port=rtsp_port,
        username=connection.username,
        password_encrypted=password_encrypted,
        rtsp_path=rtsp_path,
        sub_rtsp_path=sub_rtsp_path,
        enabled=payload.enabled,
        auto_record=payload.auto_record,
        recording_schedule_enabled=payload.recording_schedule_enabled,
        recording_schedule=[item.model_dump() for item in payload.recording_schedule],
        timestamp_mode=payload.timestamp_mode,
    )


def _write_create_connection(
    camera: Camera,
    connection: ManualRtspConnectionCreate | OnvifConnectionCreate | HikConnectionCreate,
    *,
    password_encrypted: str,
) -> None:
    if isinstance(connection, ManualRtspConnectionCreate):
        upsert_manual_rtsp_connection(
            camera,
            host=connection.host,
            port=connection.port,
            username=connection.username,
            password_encrypted=password_encrypted,
            main_path=connection.main_path,
            sub_path=connection.sub_path,
        )
        return
    if isinstance(connection, OnvifConnectionCreate):
        upsert_onvif_connection(
            camera,
            host=connection.host,
            username=connection.username,
            password_encrypted=password_encrypted,
            device_service_url=_onvif_device_service_url(
                connection.host,
                connection.port,
                connection.device_service_url,
            ),
        )
        return
    upsert_hik_connection(
        camera,
        host=connection.host,
        username=connection.username,
        password_encrypted=password_encrypted,
        sdk_port=connection.sdk_port,
        channel=connection.channel,
        main_stream_type=connection.main_stream_type,
        sub_stream_type=connection.sub_stream_type,
    )


def _mark_probe_success(camera: Camera, result: CameraConnectionProbeResult) -> None:
    now = datetime.now(timezone.utc)
    apply_probe_success(camera, result, verified_at=now)
    camera.status = "online"
    camera.last_probe_at = now
    camera.last_online_at = now


async def create_unified_camera(
    payload: CameraUnifiedCreate,
    db: AsyncSession,
    *,
    probe_result: CameraConnectionProbeResult | None = None,
) -> Camera:
    password_encrypted = encrypt_secret(payload.connection.password)
    camera = _seed_camera(payload, password_encrypted)
    _write_create_connection(
        camera,
        payload.connection,
        password_encrypted=password_encrypted,
    )
    if probe_result is not None:
        _mark_probe_success(camera, probe_result)

    db.add(camera)
    try:
        await db.flush()
        add_event(
            db,
            level="info",
            category="camera",
            code="camera.created",
            message=f"摄像头 {camera.name} 已创建",
            camera_id=camera.id,
            metadata={"adapter": camera.connection_type},
        )
        add_audit_event(
            db,
            code="operations.camera_created",
            message=f"摄像头 {camera.name} 已创建",
            camera_id=camera.id,
            metadata={"adapter": camera.connection_type},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="camera name already exists") from exc
    await db.refresh(camera)
    return camera


def _apply_camera_fields(camera: Camera, payload: CameraUnifiedUpdate) -> tuple[bool, bool]:
    values = payload.model_dump(exclude_unset=True, exclude={"connection"})

    if "recording_schedule" in values and values["recording_schedule"] is not None:
        schedule = values["recording_schedule"]
        values["recording_schedule"] = [
            item.model_dump() if hasattr(item, "model_dump") else item for item in schedule
        ]

    def changes(field: str) -> bool:
        if field not in values or values[field] is None:
            return False
        return getattr(camera, field) != values[field]

    policy_changed = any(changes(field) for field in _RUNTIME_POLICY_FIELDS)
    schedule_changed = any(changes(field) for field in _SCHEDULE_FIELDS)

    for key, value in values.items():
        if key in {"manufacturer", "model"}:
            setattr(camera, key, value)
        elif value is not None:
            setattr(camera, key, value)

    if camera.form_factor == "unknown":
        camera.form_factor = _resolved_form_factor(
            camera.manufacturer,
            camera.model,
            camera.form_factor,
        )
    if camera.recording_schedule_enabled and not camera.recording_schedule:
        raise HTTPException(
            status_code=422,
            detail="启用录制时段后至少需要配置一个时间段",
        )
    return policy_changed, schedule_changed


def _desired_password_encrypted(camera: Camera, draft, *, switching: bool) -> str:
    if draft.password is None:
        if switching:
            raise HTTPException(
                status_code=422,
                detail="target adapter password is required for a cross-adapter switch",
            )
        connection = camera.connection
        if connection is None:
            raise HTTPException(status_code=409, detail="camera has no current connection")
        return connection.password_encrypted
    return encrypt_secret(draft.password)


def _upsert_same_adapter(camera: Camera, draft, password_encrypted: str):
    if isinstance(draft, ManualRtspConnectionUpdate):
        return upsert_manual_rtsp_connection(
            camera,
            host=draft.host,
            port=draft.port,
            username=draft.username,
            password_encrypted=password_encrypted,
            main_path=draft.main_path,
            sub_path=draft.sub_path,
        )
    if isinstance(draft, OnvifConnectionUpdate):
        return upsert_onvif_connection(
            camera,
            host=draft.host,
            username=draft.username,
            password_encrypted=password_encrypted,
            device_service_url=_onvif_device_service_url(
            draft.host,
            draft.port,
            draft.device_service_url,
        ),
        )
    return upsert_hik_connection(
        camera,
        host=draft.host,
        username=draft.username,
        password_encrypted=password_encrypted,
        sdk_port=draft.sdk_port,
        channel=draft.channel,
        main_stream_type=draft.main_stream_type,
        sub_stream_type=draft.sub_stream_type,
    )


def _switch_adapter(camera: Camera, draft, password_encrypted: str):
    if isinstance(draft, ManualRtspConnectionUpdate):
        return switch_to_manual_rtsp_connection(
            camera,
            host=draft.host,
            port=draft.port,
            username=draft.username,
            password_encrypted=password_encrypted,
            main_path=draft.main_path,
            sub_path=draft.sub_path,
        )
    if isinstance(draft, OnvifConnectionUpdate):
        return switch_to_onvif_connection(
            camera,
            host=draft.host,
            username=draft.username,
            password_encrypted=password_encrypted,
            device_service_url=_onvif_device_service_url(
                draft.host,
                draft.port,
                draft.device_service_url,
            ),
        )
    return switch_to_hik_connection(
        camera,
        host=draft.host,
        username=draft.username,
        password_encrypted=password_encrypted,
        sdk_port=draft.sdk_port,
        channel=draft.channel,
        main_stream_type=draft.main_stream_type,
        sub_stream_type=draft.sub_stream_type,
    )


async def update_unified_camera(
    camera_id: int,
    payload: CameraUnifiedUpdate,
    db: AsyncSession,
    *,
    probe_result: CameraConnectionProbeResult | None = None,
    coordinator=None,
) -> Camera:
    runtime_coordinator = coordinator or camera_runtime_coordinator
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    current = camera.connection
    if current is None:
        raise HTTPException(status_code=409, detail="camera has no current connection")

    policy_changed, schedule_changed = _apply_camera_fields(camera, payload)
    draft = payload.connection
    if draft is None:
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail="camera name already exists") from exc
        await db.refresh(camera)
        if policy_changed:
            await runtime_coordinator.reload(
                camera.id,
                schedule_changed=schedule_changed,
            )
        return camera

    switching = current.adapter != draft.adapter
    password_encrypted = _desired_password_encrypted(camera, draft, switching=switching)

    if not switching:
        before_revision = current.revision
        written = _upsert_same_adapter(camera, draft, password_encrypted)
        connection_changed = written.revision != before_revision
        if probe_result is not None:
            _mark_probe_success(camera, probe_result)
        elif connection_changed:
            camera.status = "unknown"
            camera.last_probe_at = None
        add_event(
            db,
            level="info",
            category="camera",
            code="camera.updated",
            message=f"摄像头 {camera.name} 配置已更新",
            camera_id=camera.id,
        )
        add_audit_event(
            db,
            code="operations.camera_updated",
            message=f"摄像头 {camera.name} 配置已更新",
            camera_id=camera.id,
            metadata={"adapter": written.adapter},
        )
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail="camera name already exists") from exc
        await db.refresh(camera)
        if connection_changed or policy_changed or probe_result is not None:
            await runtime_coordinator.reload(
                camera.id,
                schedule_changed=schedule_changed,
            )
        return camera

    snapshot = await runtime_coordinator.stop_all(camera.id)
    try:
        written = _switch_adapter(camera, draft, password_encrypted)
        if probe_result is not None:
            _mark_probe_success(camera, probe_result)
        else:
            camera.status = "unknown"
            camera.last_probe_at = None
        add_event(
            db,
            level="info",
            category="camera",
            code="camera.updated",
            message=f"摄像头 {camera.name} 配置已更新",
            camera_id=camera.id,
        )
        add_audit_event(
            db,
            code="operations.camera_updated",
            message=f"摄像头 {camera.name} 已切换连接适配器",
            camera_id=camera.id,
            metadata={"adapter": written.adapter},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        await runtime_coordinator.restore(
            camera_id,
            snapshot,
            schedule_changed=schedule_changed,
        )
        raise HTTPException(status_code=409, detail="camera name already exists") from exc
    except Exception:
        await db.rollback()
        await runtime_coordinator.restore(
            camera_id,
            snapshot,
            schedule_changed=schedule_changed,
        )
        raise

    await db.refresh(camera)
    await runtime_coordinator.restore(
        camera.id,
        snapshot,
        schedule_changed=schedule_changed,
    )
    return camera
