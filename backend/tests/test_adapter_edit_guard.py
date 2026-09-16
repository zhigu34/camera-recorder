from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import cameras as cameras_api
from app.schemas.camera import CameraUpdate


class FakeDb:
    async def get(self, _model, _camera_id):
        return SimpleNamespace(id=9, connection_type="hik_sdk")


@pytest.mark.asyncio
async def test_generic_camera_update_rejects_hik_sdk_camera() -> None:
    with pytest.raises(HTTPException) as caught:
        await cameras_api.update_camera(
            9,
            CameraUpdate(name="must-use-hik-endpoint"),
            db=FakeDb(),
        )

    assert caught.value.status_code == 409
    assert "HIK" in str(caught.value.detail) or "adapter" in str(caught.value.detail).lower()
