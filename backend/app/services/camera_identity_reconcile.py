from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.services.camera_identity import infer_camera_form_factor


async def reconcile_camera_form_factors(session: AsyncSession) -> int:
    """Backfill only unknown camera shapes using current high-confidence rules.

    This is intentionally idempotent and runs at startup so expanding the model
    catalog in a future release automatically benefits existing cameras without
    overwriting any form factor selected by the user.
    """

    cameras = list(
        await session.scalars(
            select(Camera).where(Camera.form_factor == "unknown").order_by(Camera.id)
        )
    )
    updated = 0
    for camera in cameras:
        guess = infer_camera_form_factor(camera.manufacturer, camera.model)
        if guess is None or guess.confidence != "high":
            continue
        camera.form_factor = guess.form_factor
        updated += 1
    return updated
