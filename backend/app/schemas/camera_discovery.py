from __future__ import annotations

from pydantic import BaseModel, Field


class OnvifDiscoveryCandidate(BaseModel):
    endpoint_reference: str | None = None
    xaddrs: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    device_service_url: str | None = None
    host: str | None = None
    port: int | None = None
    selectable: bool = False
    unavailable_reason: str | None = None
    source_host: str | None = Field(default=None, exclude=True)


class OnvifDiscoveryResponse(BaseModel):
    devices: list[OnvifDiscoveryCandidate] = Field(default_factory=list)
    scan_duration_ms: int = 0
    warnings: list[str] = Field(default_factory=list)


class RtspDiscoveryCandidate(BaseModel):
    host: str
    port: int = 554
    selectable: bool = True


class RtspDiscoveryResponse(BaseModel):
    network: str
    devices: list[RtspDiscoveryCandidate] = Field(default_factory=list)
    scan_duration_ms: int = 0
    warnings: list[str] = Field(default_factory=list)
