from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from hik_bridge.sdk import HcNetSdk
from hik_bridge.service import HikBridgeError, HikBridgeService, StreamRequest


class ProbePayload(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=8000, ge=1, le=65535)
    username: str = Field(default="admin", max_length=128)
    password: str = Field(min_length=1, max_length=512)


class StreamPayload(ProbePayload):
    channel: int = Field(default=1, ge=1, le=65535)
    stream_type: int = Field(default=0, ge=0, le=10)


def _http_error(exc: HikBridgeError) -> HTTPException:
    code = 404 if "not found" in str(exc).lower() else 503
    return HTTPException(status_code=code, detail=str(exc))


def create_app(service: HikBridgeService | None = None) -> FastAPI:
    bridge = service or HikBridgeService(HcNetSdk())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await bridge.start()
        try:
            yield
        finally:
            await bridge.stop()

    app = FastAPI(title="Camera Recorder HIK Bridge", lifespan=lifespan)
    app.state.bridge = bridge

    @app.get("/health")
    async def health():
        return {"ok": True, "runtime_available": bridge.runtime_available}

    @app.post("/probe")
    async def probe(payload: ProbePayload):
        try:
            return await bridge.probe(
                payload.host,
                payload.port,
                payload.username,
                payload.password,
            )
        except HikBridgeError as exc:
            raise _http_error(exc) from exc

    @app.post("/streams", status_code=status.HTTP_201_CREATED)
    async def create_stream(payload: StreamPayload):
        try:
            stream_id = await bridge.create_stream(StreamRequest(**payload.model_dump()))
            return {"stream_id": stream_id}
        except HikBridgeError as exc:
            raise _http_error(exc) from exc

    @app.get("/streams/{stream_id}/media")
    async def stream_media(stream_id: str):
        try:
            bridge.require_stream(stream_id)
        except HikBridgeError as exc:
            raise _http_error(exc) from exc
        return StreamingResponse(
            bridge.iter_stream(stream_id),
            media_type="application/octet-stream",
        )

    @app.delete("/streams/{stream_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_stream(stream_id: str):
        await bridge.stop_stream(stream_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


app = create_app()
