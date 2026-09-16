FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HIK_SDK_PATH=/opt/hikvision/runtime \
    LD_LIBRARY_PATH=/opt/hikvision/runtime:/opt/hikvision/runtime/HCNetSDKCom

WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.116,<1" "uvicorn[standard]>=0.35,<1"
COPY hik_bridge /app/hik_bridge

EXPOSE 8100
CMD ["uvicorn", "hik_bridge.app:app", "--host", "0.0.0.0", "--port", "8100"]
