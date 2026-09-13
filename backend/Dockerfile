FROM python:3.12-slim

ARG TARGETARCH
ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG PYPI_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PYPI_INDEX_URL} \
    UV_DEFAULT_INDEX=${PYPI_INDEX_URL}

# Prefer mainland China mirrors during image builds. Keep the original Debian
# sources as an automatic fallback so a temporary mirror outage/403 cannot make
# deployments fail. Debian 12+ images normally use DEB822 sources, while older
# variants may still use sources.list.
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      cp /etc/apt/sources.list.d/debian.sources /tmp/debian.sources.orig; \
      sed -i \
        -e "s|https\?://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|https\?://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|https\?://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      cp /etc/apt/sources.list /tmp/sources.list.orig; \
      sed -i \
        -e "s|https\?://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|https\?://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|https\?://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list; \
    fi; \
    if ! apt-get -o Acquire::Retries=3 -o Acquire::http::Pipeline-Depth=0 update; then \
      echo "Preferred Debian mirror unavailable; falling back to official Debian sources" >&2; \
      rm -rf /var/lib/apt/lists/*; \
      if [ -f /tmp/debian.sources.orig ]; then \
        cp /tmp/debian.sources.orig /etc/apt/sources.list.d/debian.sources; \
      fi; \
      if [ -f /tmp/sources.list.orig ]; then \
        cp /tmp/sources.list.orig /etc/apt/sources.list; \
      fi; \
      apt-get -o Acquire::Retries=3 -o Acquire::http::Pipeline-Depth=0 update; \
    fi; \
    apt-get -o Acquire::Retries=3 -o Acquire::http::Pipeline-Depth=0 install -y --no-install-recommends \
      ca-certificates xz-utils tzdata; \
    rm -rf /var/lib/apt/lists/* /tmp/debian.sources.orig /tmp/sources.list.orig

# FFmpeg is intentionally supplied from the host build context instead of being
# downloaded during docker build. This avoids GitHub connectivity becoming a
# dependency of every image build. Prepare the archive with:
#   bash scripts/download-ffmpeg.sh auto
COPY vendor/ffmpeg/ /tmp/ffmpeg-dist/
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) FFMPEG_ARCHIVE="/tmp/ffmpeg-dist/ffmpeg-linux64.tar.xz" ;; \
      arm64) FFMPEG_ARCHIVE="/tmp/ffmpeg-dist/ffmpeg-linuxarm64.tar.xz" ;; \
      *) echo "Unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    if [ ! -s "${FFMPEG_ARCHIVE}" ]; then \
      echo "ERROR: local FFmpeg archive is missing: ${FFMPEG_ARCHIVE}" >&2; \
      echo "Run on the host before building: bash scripts/download-ffmpeg.sh ${TARGETARCH}" >&2; \
      exit 1; \
    fi; \
    mkdir -p /tmp/ffmpeg; \
    tar -xJf "${FFMPEG_ARCHIVE}" -C /tmp/ffmpeg --strip-components=1; \
    install -m 0755 /tmp/ffmpeg/bin/ffmpeg /usr/local/bin/ffmpeg; \
    install -m 0755 /tmp/ffmpeg/bin/ffprobe /usr/local/bin/ffprobe; \
    rm -rf /tmp/ffmpeg /tmp/ffmpeg-dist; \
    ffmpeg -hide_banner -h bsf=setts 2>&1 | grep -q prescale

RUN pip install --no-cache-dir uv

WORKDIR /app/backend
COPY backend/pyproject.toml ./pyproject.toml
RUN uv sync --no-dev --no-install-project

COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations

ENV PATH="/app/backend/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
