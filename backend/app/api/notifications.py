from fastapi import APIRouter, HTTPException

from app.services.email_notifier import email_notifier

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/email")
async def email_status() -> dict:
    return email_notifier.status()


@router.post("/email/test")
async def test_email() -> dict:
    status = email_notifier.status()
    if not status["enabled"]:
        raise HTTPException(status_code=409, detail="email notifications are disabled")
    if not status["configured"]:
        raise HTTPException(status_code=409, detail="SMTP configuration is incomplete")

    sent = await email_notifier.send_test()
    if not sent:
        raise HTTPException(status_code=502, detail="test email failed; check event/log output")
    return {"sent": True}
