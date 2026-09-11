FROM python:3.12-slim

ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl xz-utils tzdata \
    && rm -rf /var/lib/apt/lists/*

# Use a current static FFmpeg build because Camera Recorder depends on the
# setts bitstream filter's `prescale` option. BtbN publishes both amd64 and
# arm64 builds, so this also works natively on Apple Silicon Docker Desktop.
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) FFMPEG_ARCH="linux64" ;; \
      arm64) FFMPEG_ARCH="linuxarm64" ;; \
      *) echo "Unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    mkdir -p /tmp/ffmpeg; \
    curl -fsSL "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-${FFMPEG_ARCH}-gpl.tar.xz" \
      -o /tmp/ffmpeg.tar.xz; \
    tar -xJf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg --strip-components=1; \
    install -m 0755 /tmp/ffmpeg/bin/ffmpeg /usr/local/bin/ffmpeg; \
    install -m 0755 /tmp/ffmpeg/bin/ffprobe /usr/local/bin/ffprobe; \
    rm -rf /tmp/ffmpeg /tmp/ffmpeg.tar.xz; \
    ffmpeg -hide_banner -h bsf=setts 2>&1 | grep -q prescale

RUN pip install --no-cache-dir uv

WORKDIR /app/backend
COPY backend/pyproject.toml ./pyproject.toml
RUN uv sync --no-dev --no-install-project

COPY backend/app ./app

ENV PATH="/app/backend/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
