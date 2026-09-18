from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PHASE1_HEAD = "20260916_0022"
ONVIF_CONNECTION_REVISION = "20260916_0023"
HIK_CONNECTION_REVISION = "20260917_0024"
UNVERIFIED_ONVIF_REVISION = "20260917_0025"
ONVIF_IDENTITY_REVISION = "20260918_0026"


def _database_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _alembic(db_path: Path, revision: str) -> None:
    env = os.environ.copy()
    env["CAMREC_DATABASE_URL"] = _database_url(db_path)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def test_0023_adds_empty_onvif_config_without_mutating_existing_connection_or_legacy_metadata(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "onvif-config.db"
    _alembic(db_path, PHASE1_HEAD)

    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO cameras (
                id, name, ip, rtsp_port, username, password_encrypted, rtsp_path,
                sub_rtsp_path, enabled, auto_record, timestamp_mode, status,
                connection_type
            ) VALUES (
                41, 'migration-rtsp', '192.0.2.41', 8554, 'viewer',
                'ciphertext-41', '/main', '/sub', 1, 0, 'reconstruct',
                'unknown', 'manual_rtsp'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO camera_connections (
                id, camera_id, adapter, host, username, password_encrypted,
                revision, verification_status
            ) VALUES (
                401, 41, 'manual_rtsp', '192.0.2.41', 'viewer',
                'ciphertext-41', 3, 'verified'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO rtsp_connection_configs (
                connection_id, port, main_path, sub_path
            ) VALUES (401, 8554, '/main', '/sub')
            """
        )
        connection.execute(
            """
            INSERT INTO onvif_device_metadata (
                camera_id, device_service_url, device_uuid,
                capabilities_json, profiles_json,
                recording_profile_token, preview_profile_token,
                detection_profile_token, recording_uri, preview_uri, detection_uri
            ) VALUES (
                41, 'http://legacy/onvif/device_service', 'legacy-uuid',
                '{}', '[]', 'legacy-main', 'legacy-sub', 'legacy-sub',
                'rtsp://legacy/main', 'rtsp://legacy/sub', 'rtsp://legacy/sub'
            )
            """
        )
        connection.commit()

        before_connection = tuple(
            connection.execute(
                """
                SELECT id, camera_id, adapter, host, username, password_encrypted,
                       revision, verification_status
                FROM camera_connections WHERE id = 401
                """
            ).fetchone()
        )
        before_rtsp = tuple(
            connection.execute(
                """
                SELECT connection_id, port, main_path, sub_path
                FROM rtsp_connection_configs WHERE connection_id = 401
                """
            ).fetchone()
        )
        before_legacy_onvif = tuple(
            connection.execute(
                """
                SELECT camera_id, device_service_url, device_uuid,
                       recording_profile_token, recording_uri
                FROM onvif_device_metadata WHERE camera_id = 41
                """
            ).fetchone()
        )

    _alembic(db_path, ONVIF_CONNECTION_REVISION)

    with _connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            ONVIF_CONNECTION_REVISION
        )
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "onvif_connection_configs" in tables
        assert connection.execute("SELECT COUNT(*) FROM onvif_connection_configs").fetchone()[0] == 0
        assert tuple(
            connection.execute(
                """
                SELECT id, camera_id, adapter, host, username, password_encrypted,
                       revision, verification_status
                FROM camera_connections WHERE id = 401
                """
            ).fetchone()
        ) == before_connection
        assert tuple(
            connection.execute(
                """
                SELECT connection_id, port, main_path, sub_path
                FROM rtsp_connection_configs WHERE connection_id = 401
                """
            ).fetchone()
        ) == before_rtsp
        assert tuple(
            connection.execute(
                """
                SELECT camera_id, device_service_url, device_uuid,
                       recording_profile_token, recording_uri
                FROM onvif_device_metadata WHERE camera_id = 41
                """
            ).fetchone()
        ) == before_legacy_onvif


def test_0025_allows_unverified_onvif_cache_without_rewriting_existing_values(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "onvif-unverified.db"
    _alembic(db_path, HIK_CONNECTION_REVISION)

    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO cameras (
                id, name, ip, rtsp_port, username, password_encrypted, rtsp_path,
                enabled, auto_record, timestamp_mode, status, connection_type
            ) VALUES (
                51, 'verified-onvif', '192.0.2.51', 554, 'viewer',
                'ciphertext-51', '/main', 1, 0, 'reconstruct', 'online', 'onvif'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO camera_connections (
                id, camera_id, adapter, host, username, password_encrypted,
                revision, verification_status
            ) VALUES (
                501, 51, 'onvif', '192.0.2.51', 'viewer',
                'ciphertext-51', 4, 'verified'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO onvif_connection_configs (
                connection_id, device_service_url, device_uuid,
                capabilities_json, profiles_json,
                recording_profile_token, preview_profile_token,
                detection_profile_token, recording_uri, preview_uri, detection_uri
            ) VALUES (
                501, 'http://192.0.2.51:80/onvif/device_service', 'uuid-51',
                '{}', '[]', 'main', 'sub', 'sub',
                'rtsp://192.0.2.51/main', 'rtsp://192.0.2.51/sub', 'rtsp://192.0.2.51/sub'
            )
            """
        )
        connection.commit()
        before = tuple(
            connection.execute(
                """
                SELECT connection_id, device_service_url, device_uuid,
                       recording_profile_token, recording_uri
                FROM onvif_connection_configs WHERE connection_id = 501
                """
            ).fetchone()
        )

    _alembic(db_path, UNVERIFIED_ONVIF_REVISION)

    with _connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            UNVERIFIED_ONVIF_REVISION
        )
        columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(onvif_connection_configs)")
        }
        assert columns["recording_profile_token"][3] == 0
        assert columns["recording_uri"][3] == 0
        assert tuple(
            connection.execute(
                """
                SELECT connection_id, device_service_url, device_uuid,
                       recording_profile_token, recording_uri
                FROM onvif_connection_configs WHERE connection_id = 501
                """
            ).fetchone()
        ) == before



def test_0026_adds_onvif_identity_columns_without_rewriting_existing_config(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "onvif-identity.db"
    _alembic(db_path, UNVERIFIED_ONVIF_REVISION)

    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO cameras (
                id, name, ip, rtsp_port, username, password_encrypted, rtsp_path,
                enabled, auto_record, timestamp_mode, status, connection_type
            ) VALUES (
                61, 'identity-onvif', '192.0.2.61', 554, 'viewer',
                'ciphertext-61', '/main', 1, 0, 'reconstruct', 'online', 'onvif'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO camera_connections (
                id, camera_id, adapter, host, username, password_encrypted,
                revision, verification_status
            ) VALUES (
                601, 61, 'onvif', '192.0.2.61', 'viewer',
                'ciphertext-61', 2, 'verified'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO onvif_connection_configs (
                connection_id, device_service_url, device_uuid,
                capabilities_json, profiles_json,
                recording_profile_token, preview_profile_token,
                detection_profile_token, recording_uri, preview_uri, detection_uri
            ) VALUES (
                601, 'http://192.0.2.61:80/onvif/device_service', 'uuid-61',
                '{"media_xaddr":"http://192.0.2.61/onvif/media"}',
                '[{"token":"main","uri":"rtsp://192.0.2.61/main"}]',
                'main', 'main', 'main',
                'rtsp://192.0.2.61/main', 'rtsp://192.0.2.61/main', 'rtsp://192.0.2.61/main'
            )
            """
        )
        connection.commit()
        before = tuple(
            connection.execute(
                """
                SELECT connection_id, device_service_url, device_uuid,
                       capabilities_json, profiles_json,
                       recording_profile_token, recording_uri
                FROM onvif_connection_configs WHERE connection_id = 601
                """
            ).fetchone()
        )

    _alembic(db_path, ONVIF_IDENTITY_REVISION)

    with _connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            ONVIF_IDENTITY_REVISION
        )
        columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(onvif_connection_configs)")
        }
        assert {"firmware_version", "serial_number", "hardware_id"} <= set(columns)
        assert columns["firmware_version"][3] == 0
        assert columns["serial_number"][3] == 0
        assert columns["hardware_id"][3] == 0
        after = tuple(
            connection.execute(
                """
                SELECT connection_id, device_service_url, device_uuid,
                       capabilities_json, profiles_json,
                       recording_profile_token, recording_uri
                FROM onvif_connection_configs WHERE connection_id = 601
                """
            ).fetchone()
        )
        assert after == before
