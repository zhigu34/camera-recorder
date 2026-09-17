from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decrypt_secret
from app.models.camera import Camera
from app.schemas.camera_connection import CameraConnectionUpdate
from app.services.camera_adapter_probe import (
    CameraAdapterProbeError,
    CameraConnectionProbeResult,
    probe_connection_draft,
)
from app.services.camera_adapter_registry import (
    CameraAdapterCapability,
    list_camera_adapter_capabilities,
)
from app.services.system_settings import load_runtime_settings

router = APIRouter(tags=["camera-connections"])


class CameraConnectionProbeRequest(BaseModel):
    camera_id: int | None = Field(default=None, ge=1)
    connection: CameraConnectionUpdate

    @model_validator(mode="after")
    def require_new_connection_password(self):
        if self.camera_id is None and self.connection.password is None:
            raise ValueError("password is required for a new connection probe")
        return self


def _stored_password(camera: Camera) -> str:
    connection = camera.connection
    encrypted = connection.password_encrypted if connection is not None else camera.password_encrypted
    try:
        return decrypt_secret(encrypted)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail="camera password cannot be decrypted; re-enter the password before probing",
        ) from exc


@router.get("/api/camera-adapters", response_model=list[CameraAdapterCapability])
async def list_camera_adapters() -> list[CameraAdapterCapability]:
    return await list_camera_adapter_capabilities()


@router.post("/api/camera-connections/probe", response_model=CameraConnectionProbeResult)
async def probe_camera_connection(
    payload: CameraConnectionProbeRequest,
    db: AsyncSession = Depends(get_db),
) -> CameraConnectionProbeResult:
    draft = payload.connection
    password = draft.password

    if password is None:
        if payload.camera_id is None:
            raise HTTPException(status_code=422, detail="password is required")
        camera = await db.get(Camera, payload.camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="camera not found")
        current_adapter = camera.connection.adapter if camera.connection is not None else camera.connection_type
        if current_adapter != draft.adapter:
            raise HTTPException(
                status_code=422,
                detail="target adapter password is required for a cross-adapter probe",
            )
        password = _stored_password(camera)

    runtime = await load_runtime_settings(db)
    try:
        return await probe_connection_draft(
            draft,
            password=password,
            rtsp_timeout_us=runtime.rtsp_timeout_us,
        )
    except CameraAdapterProbeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
