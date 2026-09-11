import asyncio
from contextlib import suppress
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.models.camera import Camera
from app.services.camera_preview import resolve_preview_path
from app.services.preview_wall import WallPreviewSource, stream_preview_frames
from app.services.system_settings import load_runtime_settings

router = APIRouter(tags=["preview-wall"])


class WallSlotRequest(BaseModel):
    index: int = Field(ge=0, le=8)
    camera_id: int = Field(gt=0)
    stream: Literal["auto", "sub", "main"] = "auto"


class WallStartRequest(BaseModel):
    fps: int = Field(default=5, ge=1, le=8)
    width: int = Field(default=640, ge=320, le=1280)
    slots: list[WallSlotRequest] = Field(default_factory=list, max_length=9)


def _source_for_camera(
    *,
    camera: Camera,
    password: str,
    rtsp_path: str,
    rtsp_timeout_us: int,
    fps: int,
    width: int,
) -> WallPreviewSource:
    return WallPreviewSource(
        ip=camera.ip,
        port=camera.rtsp_port,
        username=camera.username,
        password=password,
        rtsp_path=rtsp_path,
        rtsp_timeout_us=rtsp_timeout_us,
        fps=fps,
        width=width,
    )


@router.websocket("/ws/preview-wall")
async def preview_wall(websocket: WebSocket) -> None:
    await websocket.accept()
    send_lock = asyncio.Lock()
    tasks: list[asyncio.Task] = []

    async def send_json(payload: dict) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def stream_slot(
        slot: WallSlotRequest,
        source: WallPreviewSource,
        fallback: WallPreviewSource | None,
    ) -> None:
        sent_first = False

        async def on_frame(frame: bytes) -> None:
            nonlocal sent_first
            payload = bytes([slot.index]) + frame
            async with send_lock:
                await websocket.send_bytes(payload)
            if not sent_first:
                sent_first = True
                await send_json({"type": "slot_ready", "slot": slot.index})

        try:
            await stream_preview_frames(source, on_frame)
        except asyncio.CancelledError:
            raise
        except Exception as primary_exc:
            if fallback is not None:
                with suppress(Exception):
                    await send_json({
                        "type": "slot_fallback",
                        "slot": slot.index,
                        "detail": "子码流不可用，已自动切换主码流",
                    })
                try:
                    await stream_preview_frames(fallback, on_frame)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as fallback_exc:
                    primary_exc = RuntimeError(
                        f"子码流与主码流均无法预览: {fallback_exc}"
                    )
            with suppress(Exception):
                await send_json({
                    "type": "slot_error",
                    "slot": slot.index,
                    "detail": str(primary_exc),
                })

    try:
        try:
            request = WallStartRequest.model_validate(await websocket.receive_json())
        except Exception:
            await send_json({"type": "fatal", "detail": "无效的多画面预览配置"})
            await websocket.close(code=1008)
            return

        seen_indexes: set[int] = set()
        seen_cameras: set[int] = set()
        for slot in request.slots:
            if slot.index in seen_indexes or slot.camera_id in seen_cameras:
                await send_json({"type": "fatal", "detail": "多画面槽位或摄像头配置重复"})
                await websocket.close(code=1008)
                return
            seen_indexes.add(slot.index)
            seen_cameras.add(slot.camera_id)

        async with SessionLocal() as db:
            runtime = await load_runtime_settings(db)
            resolved: list[
                tuple[WallSlotRequest, WallPreviewSource, WallPreviewSource | None]
            ] = []
            for slot in request.slots:
                camera = await db.get(Camera, slot.camera_id)
                if camera is None or not camera.enabled:
                    await send_json({
                        "type": "slot_error",
                        "slot": slot.index,
                        "detail": "摄像头不存在或未启用",
                    })
                    continue
                try:
                    password = decrypt_secret(camera.password_encrypted)
                    rtsp_path, selected_stream = resolve_preview_path(
                        main_path=camera.rtsp_path,
                        sub_path=camera.sub_rtsp_path,
                        stream=slot.stream,
                    )
                except Exception as exc:
                    await send_json({
                        "type": "slot_error",
                        "slot": slot.index,
                        "detail": str(exc),
                    })
                    continue

                source = _source_for_camera(
                    camera=camera,
                    password=password,
                    rtsp_path=rtsp_path,
                    rtsp_timeout_us=runtime.rtsp_timeout_us,
                    fps=request.fps,
                    width=request.width,
                )
                fallback = None
                if slot.stream == "auto" and selected_stream == "sub":
                    fallback = _source_for_camera(
                        camera=camera,
                        password=password,
                        rtsp_path=camera.rtsp_path,
                        rtsp_timeout_us=runtime.rtsp_timeout_us,
                        fps=request.fps,
                        width=request.width,
                    )
                resolved.append((slot, source, fallback))

        for slot, source, fallback in resolved:
            tasks.append(asyncio.create_task(stream_slot(slot, source, fallback)))

        await send_json({
            "type": "started",
            "slots": [slot.index for slot, _, _ in resolved],
        })

        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
