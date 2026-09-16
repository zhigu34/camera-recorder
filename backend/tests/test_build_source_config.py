from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dockerfiles_default_to_official_package_sources() -> None:
    backend = _read("backend/Dockerfile")
    frontend = _read("frontend/Dockerfile")

    assert "ARG DEBIAN_MIRROR=http://deb.debian.org/debian" in backend
    assert "ARG DEBIAN_SECURITY_MIRROR=http://deb.debian.org/debian-security" in backend
    assert "ARG PYPI_INDEX_URL=https://pypi.org/simple" in backend
    assert "ARG NPM_REGISTRY=https://registry.npmjs.org" in frontend


def test_compose_exposes_build_source_overrides_from_env() -> None:
    compose = _read("docker-compose.yml")

    assert "DEBIAN_MIRROR: ${DEBIAN_MIRROR:-http://deb.debian.org/debian}" in compose
    assert (
        "DEBIAN_SECURITY_MIRROR: "
        "${DEBIAN_SECURITY_MIRROR:-http://deb.debian.org/debian-security}"
    ) in compose
    assert "PYPI_INDEX_URL: ${PYPI_INDEX_URL:-https://pypi.org/simple}" in compose
    assert "NPM_REGISTRY: ${NPM_REGISTRY:-https://registry.npmjs.org}" in compose


def test_env_example_keeps_mainland_mirror_overrides_for_local_deployments() -> None:
    env_example = _read(".env.example")

    assert "DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian" in env_example
    assert (
        "DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security"
        in env_example
    )
    assert "PYPI_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple" in env_example
    assert "NPM_REGISTRY=https://registry.npmmirror.com" in env_example
